"""질문 답변 서비스 답 단계 — 저장 시간 제한·금액 안전망·추가 검토 회귀 (test_ask_service_answer 에서 나눔, 200줄 관문).

정본 docs/str/03 9·10 단계 · 06 "질문 답변에 도는 코드 검사". SCRUM-362 — 문장 해석 회귀(SCRUM-290 추가 검토 2~6)는
"직접 쓴 숫자·날짜 → UNVERIFIED(응답에 본문 없음) / 같은 사실을 자리표로 → ANSWERED" 로 바뀜.
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
    """추가 검토 2 high(SCRUM-290) — "999 자금세탁 확정 USD" → 자리표 밖 숫자로 UNVERIFIED, 응답·저장 response 에 문구 없음."""
    body = "입금은 999 자금세탁 확정 USD 예요. {{inbound.amount.USD|이에요}}"
    llm = StubLlm([FLOWS, answer_text(True, body)])
    svc, repo = build_service(llm)
    res = svc.ask(ask_request(Q))
    assert res.status is AskStatus.UNVERIFIED
    assert res.code_checks[0].draft_value == "자리표 밖 숫자 1개"
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


_GAPS = [" ", "  ", "\t", "\u3000", "\u00a0", "\u2002", "\u2003", "\u2009", " \u3000\t\u00a0"]


@pytest.mark.parametrize("gap", _GAPS, ids=lambda g: repr(g))
@pytest.mark.parametrize("day", ["2021-03-14", "2022-09-02"])
def test_written_trade_start_date_is_unverified_and_hidden(gap: str, day: str) -> None:
    """추가 검토 3~6 high(SCRUM-290 — 거래 시작일·공백 변형)의 v3 꼴: 맞는 날짜도 직접 쓰면 UNVERIFIED, 본문은 응답에 없음.

    onboarded_at(2021-03-14)이 있는 fan_in 픽스처 — 예전엔 개설일·기간 대조가 낱말 사이 공백에 따라 갈렸던 문장.
    """
    body = f"고객의 입금{gap}거래 시작일은 {day}이에요."
    fan_in = Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))
    llm = StubLlm([FLOWS, answer_text(True, body)])
    svc, repo = build_service(llm, facts=fan_in)
    res = svc.ask(ask_request("입금 거래는 언제 시작됐어?"))
    assert res.status is AskStatus.UNVERIFIED and res.answer is None
    assert res.code_checks[0].draft_value.startswith("자리표 밖 숫자")  # 날짜 숫자가 먼저 걸림(06 표 순서)
    saved = repo.saved[0]["response_payload"]
    public = json.dumps({k: v for k, v in saved.items() if k != "llm_answer"}, ensure_ascii=False)
    assert day not in public and saved["answer"] is None


@pytest.mark.parametrize("question", ["입금 거래는 언제 시작됐어?", "고객과 언제부터 거래했어?"])
def test_period_slot_answers_with_label(question: str) -> None:
    """같은 질문을 자리표로 — 기간·등록일이 이름표와 함께 나가 개설일/기간 혼동이 문장에 안 생김."""
    fan_in = Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))
    body = "{{period|이에요}} {{customer.onboarded_at|이에요}}"
    llm = StubLlm([plan_text("FACT", None, ["flows", "subject"]), answer_text(True, body)])
    svc, _ = build_service(llm, facts=fan_in)
    res = svc.ask(ask_request(question))
    assert res.status is AskStatus.ANSWERED
    assert res.answer == (
        "거래 기간 2022년 9월 2일 00:14 ~ 2022년 9월 2일 22:51이에요 고객 등록일 2021년 3월 14일이에요"
    )
    assert res.cites == ["period", "customer.onboarded_at"]
