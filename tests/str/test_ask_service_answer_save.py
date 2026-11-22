"""질문 답변 서비스 답 단계 — 저장 시간 제한·금액 안전망·추가 검토 회귀 (test_ask_service_answer 에서 나눔, 200줄 관문).

정본 docs/str/03 9·10 단계 · 06 "질문 답변에 도는 코드 검사".
"""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.schemas.str import AskStatus, Facts
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

FLOWS = plan_text("FACT", None, ["flows"])
Q = "입금 거래는 모두 몇 건이야?"


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def test_save_gets_remaining_time_as_timeout() -> None:
    ticks = iter([0.0, 0.0, 1.0, 1.0, 2.0, 5.0, 6.0])  # 저장 직전 남은 15
    llm = StubLlm([FLOWS, answer_text()])
    svc, repo = build_service(llm, clock=lambda: next(ticks))
    svc.ask(ask_request(Q))
    (row,) = repo.saved
    assert row["status"] == "SUCCEEDED" and row["timeout_s"] == 15.0


def test_save_after_deadline_is_502_and_failed_only() -> None:
    ticks = iter([0.0, 0.0, 1.0, 1.0, 2.0, 21.0, 21.0])  # 답은 제때, 저장 직전 마감 지남
    llm = StubLlm([FLOWS, answer_text()])
    svc, repo = build_service(llm, clock=lambda: next(ticks))
    with pytest.raises(LlmUnavailable):
        svc.ask(ask_request(Q))
    assert [r["status"] for r in repo.saved] == ["FAILED"]
    assert repo.saved[0]["error"].startswith("LLM_UNAVAILABLE")


def test_deadline_passing_before_commit_is_502_and_failed_only() -> None:
    ticks = iter([0.0, 0.0, 1.0, 1.0, 2.0, 19.0, 21.0, 21.0])  # INSERT 뒤 커밋 직전 21
    llm = StubLlm([FLOWS, answer_text()])
    svc, repo = build_service(llm, clock=lambda: next(ticks))
    with pytest.raises(LlmUnavailable):
        svc.ask(ask_request(Q))
    assert [r["status"] for r in repo.saved] == ["FAILED"]


def test_amount_safety_net_korean_words_never_reach_response() -> None:
    """추가 검토 2 high — "999 자금세탁 확정 USD" → UNVERIFIED, 응답 어디에도 한글 문구 없음, 저장 행 llm_answer 에만."""
    body = "입금은 999 자금세탁 확정 USD 예요."
    llm = StubLlm([FLOWS, answer_text(True, body, ["inbound.amount.USD"])])
    svc, repo = build_service(llm)
    res = svc.ask(ask_request(Q))
    assert res.status is AskStatus.UNVERIFIED
    dumped = res.model_dump_json()
    assert "자금세탁" not in dumped and "확정" not in dumped
    saved = repo.saved[0]["response_payload"]
    assert "자금세탁" not in json.dumps(
        {k: v for k, v in saved.items() if k != "llm_answer"}, ensure_ascii=False
    )
    assert saved["llm_answer"]["answer"] == body


def test_commit_started_result_stands_even_past_deadline() -> None:
    """추가 검토 2 medium — 커밋 직전 확인을 지나면 커밋 중 마감을 넘겨도 SUCCEEDED·응답 그대로(03 정책)."""
    now = [0.0]
    llm = StubLlm([FLOWS, answer_text()])
    svc, repo = build_service(llm, clock=lambda: now[0])

    def slow_commit(**kw) -> None:
        now[0] = 19.9
        kw["before_commit"]()  # 커밋 직전 확인 통과
        now[0] = 25.0  # 커밋 왕복 중 마감(20) 지남
        repo.saved.append(kw)

    repo.save = slow_commit  # type: ignore[method-assign]
    res = svc.ask(ask_request(Q))
    assert res.status is AskStatus.ANSWERED
    assert [r["status"] for r in repo.saved] == ["SUCCEEDED"]


@pytest.mark.parametrize(
    "body, status",
    [
        ("고객의 입금 거래 시작일은 2021-03-14이에요.", AskStatus.UNVERIFIED),
        ("고객의 입금 거래 시작일은 2022-09-02이에요.", AskStatus.ANSWERED),
    ],
    ids=["onboard-date", "period-date"],
)
def test_review3_direction_word_trade_start_in_response_and_row(body: str, status: AskStatus) -> None:
    """추가 검토 3 high — 입금 문맥의 거래 시작일은 period 와 대조. 틀린 날짜는 응답·저장 response 에 없음."""
    llm = StubLlm([FLOWS, answer_text(True, body, ["period"])])
    svc, repo = build_service(llm)
    res = svc.ask(ask_request("입금 거래는 언제 시작됐어?"))
    assert res.status is status
    saved = repo.saved[0]["response_payload"]
    assert saved["status"] == status.value
    public = json.dumps({k: v for k, v in saved.items() if k != "llm_answer"}, ensure_ascii=False)
    assert (body in public) is (status is AskStatus.ANSWERED)
    date_check = next(c for c in res.code_checks if c.check.value == "DATE_MATCH")
    assert "period" in (date_check.source_value or "")


@pytest.mark.parametrize(
    "body",
    [
        "고객과의 거래 시작일은 2022-09-02이며 입금은 3건이에요.",
        "받은 자료에 따르면 고객과의 거래 시작일은 2022-09-02이에요.",
    ],
    ids=["direction-elsewhere", "badeun-jaryo"],
)
def test_review4_onboard_claim_not_answered_in_response_and_row(body: str) -> None:
    """추가 검토 4 high — 다른 곳의 방향 낱말로 개설일 오답이 ANSWERED 되지 않음, 응답·저장 response 에 본문 없음."""
    llm = StubLlm([FLOWS, answer_text(True, body, ["period"])])
    svc, repo = build_service(llm)
    res = svc.ask(ask_request("고객과 언제부터 거래했어?"))
    assert res.status is AskStatus.UNVERIFIED
    saved = repo.saved[0]["response_payload"]
    assert saved["status"] == "UNVERIFIED"
    assert body not in json.dumps({k: v for k, v in saved.items() if k != "llm_answer"}, ensure_ascii=False)
    assert any(
        c.check.value == "DATE_MATCH" and not c.match and "onboarded_at" in (c.source_value or "")
        for c in res.code_checks
    )


@pytest.mark.parametrize(
    "body, status",
    [
        ("고객의 입금  거래 시작일은 2021-03-14이에요.", AskStatus.UNVERIFIED),
        ("고객의 입금\t거래 시작일은 2021-03-14이에요.", AskStatus.UNVERIFIED),
        ("고객의 입금  거래 시작일은 2022-09-02이에요.", AskStatus.ANSWERED),
    ],
    ids=["two-spaces", "tab", "two-spaces-period"],
)
def test_review5_whitespace_gap_in_response_and_row(body: str, status: AskStatus) -> None:
    """추가 검토 5 high — 공백 2·탭이어도 방향 낱말이 꾸밈. 틀린 날짜는 응답·저장 response 에 본문 없음.

    onboarded_at(2021-03-14)이 있는 fan_in 픽스처를 주입 — 개설일로 잘못 대조되면 ANSWERED 가 됐을 문장.
    """
    llm = StubLlm([FLOWS, answer_text(True, body, ["period"])])
    fan_in = Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))
    assert fan_in.customer is not None and str(fan_in.customer.onboarded_at) == "2021-03-14"
    svc, repo = build_service(llm, facts=fan_in)
    res = svc.ask(ask_request("입금 거래는 언제 시작됐어?"))
    assert res.status is status
    (d,) = [c for c in res.code_checks if c.check.value == "DATE_MATCH"]
    assert "period" in (d.source_value or "")
    saved = repo.saved[0]["response_payload"]
    public = json.dumps({k: v for k, v in saved.items() if k != "llm_answer"}, ensure_ascii=False)
    assert (body in public) is (status is AskStatus.ANSWERED)
    assert (res.answer is None) is (status is AskStatus.UNVERIFIED)


@pytest.mark.parametrize(
    "gap",
    ["\u3000", "\u00a0", "\u2002", "\u2003", "\u2009", " \u3000\t\u00a0"],
    ids=["ideographic", "nbsp", "en", "em", "thin", "mixed"],
)
def test_review6_unicode_gap_in_response_and_row(gap: str) -> None:
    """추가 검토 6 high — 유니코드 공백이어도 방향 낱말이 꾸밈. onboarded_at 있는 fan_in 주입."""
    fan_in = Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))
    for day, status in (("2021-03-14", AskStatus.UNVERIFIED), ("2022-09-02", AskStatus.ANSWERED)):
        body = f"고객의 입금{gap}거래 시작일은 {day}이에요."
        llm = StubLlm([FLOWS, answer_text(True, body, ["period"])])
        svc, repo = build_service(llm, facts=fan_in)
        res = svc.ask(ask_request("입금 거래는 언제 시작됐어?"))
        assert res.status is status, day
        saved = repo.saved[0]["response_payload"]
        public = json.dumps({k: v for k, v in saved.items() if k != "llm_answer"}, ensure_ascii=False)
        assert saved["answer"] == (
            body if status is AskStatus.ANSWERED else None
        )  # 탭은 JSON 에서 이스케이프돼 칸으로 비교
        assert (f"거래 시작일은 {day}" in public) is (status is AskStatus.ANSWERED)
