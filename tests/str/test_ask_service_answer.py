"""AskService 290-2 — 답 단계·코드 검사·근거·상태 3종 (SCRUM-290, 03 8~10 · 06 "질문 답변").

가짜 LLM 은 응답 두 개(계획, 답)를 차례로 돌려준다. facts 는 `StubReader`(fan_in 숫자, 입금 3건·USD 42750.50).
"""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.errors import LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.schemas.str import AskStatus
from aml_ai.str.domain.constants_ask import ASK_ANSWER_PROMPT
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
        ASK_ANSWER_PROMPT,
        "ask_plan_v1",
        ["flows"],
    )
    assert (meta.tokens_in, meta.tokens_out, meta.latency_ms) == (240, 60, 1800)  # 두 호출 합
    assert [c["tag"] for c in llm.calls] == ["ask_plan_v1", ASK_ANSWER_PROMPT]
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
    assert row["meta"]["prompt_version"] == ASK_ANSWER_PROMPT


def test_not_answerable_is_no_data_and_ignores_answer() -> None:
    llm = StubLlm([FLOWS, answer_text(False, "무시될 문장 7건", ["inbound.count"])])
    svc, repo = build_service(llm)
    res = svc.ask(ask_request(Q))
    assert res.status is AskStatus.NO_DATA and res.kind.value == "FACT"
    assert (res.answer, res.cites, res.evidence_ids, res.code_checks) == (None, [], [], [])
    assert res.generation_meta.prompt_version == ASK_ANSWER_PROMPT
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
