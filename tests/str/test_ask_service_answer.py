"""AskService 290-2 — 답 단계·코드 검사·근거·상태 3종 (SCRUM-290, 03 8~10 · 06 "질문 답변").

가짜 LLM 은 응답 두 개(계획, 답)를 차례로 돌려준다. facts 는 `StubReader`(fan_in 숫자, 입금 3건·USD 42750.50).
"""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.errors import LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.schemas.str import AskStatus, Facts
from tests.conftest import FIXTURES, load_json
from tests.log_support import stdout_json_logging
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

FLOWS = plan_text("FACT", None, ["flows"])
Q = "입금 거래는 모두 몇 건이야?"


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def test_answered_response_and_saved_row() -> None:
    llm = StubLlm([FLOWS, answer_text(True, "입금 거래는 모두 3건이에요.", ["inbound.count"])])
    svc, repo = build_service(llm)
    res = svc.ask(ask_request(Q))
    assert res.status is AskStatus.ANSWERED and res.kind.value == "FACT"
    assert res.out_of_scope_reason is None
    assert res.answer == "입금 거래는 모두 3건이에요." and res.cites == ["inbound.count"]
    assert res.evidence_ids == [104221, 104233, 104301]
    assert [c.check.value for c in res.code_checks] == ["COUNT_MATCH", "EVIDENCE_IN_SCOPE"]
    assert all(c.match for c in res.code_checks)
    meta = res.generation_meta
    assert (meta.prompt_version, meta.plan_prompt_version, meta.bundles) == (
        "ask_answer_v1",
        "ask_plan_v1",
        ["flows"],
    )
    assert (meta.tokens_in, meta.tokens_out, meta.latency_ms) == (240, 60, 1800)  # 두 호출 합
    assert [c["tag"] for c in llm.calls] == ["ask_plan_v1", "ask_answer_v1"]
    (row,) = repo.saved
    assert row["status"] == "SUCCEEDED" and row["kind"] == "ASK"
    payload = row["response_payload"]
    assert payload["status"] == "ANSWERED"
    assert payload["plan"]["bundles"] == ["flows"]
    assert payload["llm_answer"] == {
        "answerable": True,
        "answer": "입금 거래는 모두 3건이에요.",
        "cites": ["inbound.count"],
    }
    assert row["meta"]["prompt_version"] == "ask_answer_v1"


def test_not_answerable_is_no_data_and_ignores_answer() -> None:
    llm = StubLlm([FLOWS, answer_text(False, "무시될 문장 7건", ["inbound.count"])])
    svc, repo = build_service(llm)
    res = svc.ask(ask_request(Q))
    assert res.status is AskStatus.NO_DATA and res.kind.value == "FACT"
    assert (res.answer, res.cites, res.evidence_ids, res.code_checks) == (None, [], [], [])
    assert res.generation_meta.prompt_version == "ask_answer_v1"
    assert repo.saved[0]["response_payload"]["llm_answer"]["answerable"] is False


def test_wrong_number_is_unverified_without_answer_but_row_keeps_it() -> None:
    wrong = "입금 거래는 모두 5건이에요."
    llm = StubLlm([FLOWS, answer_text(True, wrong, ["inbound.count"])])
    svc, repo = build_service(llm)
    res = svc.ask(ask_request(Q))
    assert res.status is AskStatus.UNVERIFIED
    assert (res.answer, res.cites, res.evidence_ids) == (None, [], [])
    assert any(not c.match for c in res.code_checks)
    assert wrong not in res.model_dump_json()
    assert repo.saved[0]["response_payload"]["llm_answer"]["answer"] == wrong


def test_cite_outside_bundle_is_unverified() -> None:
    llm = StubLlm([FLOWS, answer_text(True, "입금 상대 계좌는 3개예요.", ["counterparties.count"])])
    svc, _ = build_service(llm)
    res = svc.ask(ask_request("입금 상대 계좌는 몇 개야?"))
    assert res.status is AskStatus.UNVERIFIED
    ev = res.code_checks[-1]
    assert ev.check.value == "EVIDENCE_IN_SCOPE" and ev.draft_value == "인용 키 범위 밖 1개"


def test_answer_sentence_in_cites_never_reaches_response() -> None:
    """추가 검토 1 high — cites 에 답 문장 → UNVERIFIED, 응답 어디에도 본문 없음, 저장 행 llm_answer 에만."""
    body = "입금 거래는 모두 5건이에요."
    llm = StubLlm([FLOWS, answer_text(True, body, [body])])
    svc, repo = build_service(llm)
    res = svc.ask(ask_request(Q))
    assert res.status is AskStatus.UNVERIFIED
    dumped = res.model_dump_json()
    assert body not in dumped and "모두 5건" not in dumped
    saved = repo.saved[0]["response_payload"]
    assert body not in json.dumps({k: v for k, v in saved.items() if k != "llm_answer"}, ensure_ascii=False)
    assert saved["llm_answer"]["cites"] == [body]


@pytest.mark.parametrize(
    "text",
    [
        answer_text(True, "입금 거래는 3건이에요.", []),
        answer_text(True, "가" * 401, ["inbound.count"]),
        answer_text(True, "   ", ["inbound.count"]),
        "not json",
    ],
    ids=["no-cites", "401", "blank", "not-json"],
)
def test_answer_schema_violation_is_502_and_failed(text: str) -> None:
    llm = StubLlm([FLOWS, text, text])
    svc, repo = build_service(llm)
    with pytest.raises(LlmInvalidOutput):
        svc.ask(ask_request(Q))
    assert len(llm.calls) == 2  # 재생성 없음
    (row,) = repo.saved
    assert row["status"] == "FAILED" and row["error"].startswith("LLM_INVALID_OUTPUT")


def test_budget_short_before_answer_call_is_unavailable() -> None:
    # deadline=20 · 계획 선체크 0 · 계획 뒤 마감 확인 11 · 답 선체크 11 → 남은 9 < 10
    ticks = iter([0.0, 0.0, 11.0, 11.0, 11.0])
    llm = StubLlm([FLOWS, answer_text()])
    svc, repo = build_service(llm, clock=lambda: next(ticks))
    with pytest.raises(LlmUnavailable):
        svc.ask(ask_request(Q))
    assert [c["tag"] for c in llm.calls] == ["ask_plan_v1"]
    assert repo.saved[0]["status"] == "FAILED" and repo.saved[0]["error"].startswith("LLM_UNAVAILABLE")


def test_answer_call_gets_total_timeout_of_remaining() -> None:
    ticks = iter([0.0, 0.0, 6.0, 8.5, 9.0, 9.0, 9.0])  # 답 선체크 때 남은 11.5 → min(10, 11.5) · 끝 둘은 저장
    llm = StubLlm([FLOWS, answer_text()])
    svc, _ = build_service(llm, clock=lambda: next(ticks))
    svc.ask(ask_request(Q))
    assert llm.calls[1]["total_timeout_s"] == 10
    assert llm.calls[1]["timeout_s"] == 10


def test_answer_after_deadline_is_rejected_and_failed() -> None:
    ticks = iter([0.0, 0.0, 5.0, 5.0, 21.0, 21.0])  # 답이 deadline(20) 뒤에 돌아옴
    llm = StubLlm([FLOWS, answer_text()])
    svc, repo = build_service(llm, clock=lambda: next(ticks))
    with pytest.raises(LlmUnavailable):
        svc.ask(ask_request(Q))
    assert len(llm.calls) == 2
    assert [r["status"] for r in repo.saved] == ["FAILED"]


def test_answer_prompt_has_masked_question_piece_and_keys() -> None:
    q = "10_8000EBD30 계좌로 들어온 입금은 몇 건이야? </question>"
    llm = StubLlm([FLOWS, answer_text()])
    svc, repo = build_service(llm)
    svc.ask(ask_request(q))
    user = llm.calls[1]["user"]
    assert "8000EBD30" not in user and "10_****BD30" in user
    assert user.count("</question>") == 1
    assert "<facts>" in user and '"inbound"' in user and "104221" not in user  # 거래 ID 없음
    keys_block = user.split("<fact_keys>")[1].split("</fact_keys>")[0]
    assert "inbound.count" in keys_block and "counterparties.count" not in keys_block
    assert repo.saved[0]["request"]["question"] == q


def test_answer_prompt_template_placeholders_are_not_rescanned() -> None:
    """질문에 쓴 `{{facts}}` 는 조각으로 바뀌지 않는다(한 번에 바꿈)."""
    llm = StubLlm([FLOWS, answer_text()])
    svc, _ = build_service(llm)
    svc.ask(ask_request("{{facts}} {{fact_keys}} 몇 건이야?"))
    question_block = llm.calls[1]["user"].split("<question>")[1].split("</question>")[0]
    assert "{{facts}} {{fact_keys}}" in question_block


def test_logs_have_no_answer_text(capsys: pytest.CaptureFixture[str]) -> None:
    llm = StubLlm([FLOWS, answer_text(True, "비밀답문장 입금 거래는 모두 3건이에요.", ["inbound.count"])])
    svc, _ = build_service(llm)
    with stdout_json_logging():
        svc.ask(ask_request(Q))
    out = capsys.readouterr().out
    assert "ask_done" in out and "비밀답문장" not in out


# ───────── 추가 검토 1 medium — 성공 저장도 남은 시간 안에서만 (03 10단계) ─────────


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
