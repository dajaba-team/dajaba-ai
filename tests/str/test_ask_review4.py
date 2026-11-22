"""질문 답변 추가 검토 4 재현 — 고친 셋: H6 다른 케이스 · H1 최대·최소 표시 · H2 문장 넘는 나열 (SCRUM-358·359, 06 질문 답변 8번·04).

H3·H4·H5 는 알고 남김(08 · SCRUM-362 — 답 문장 해석으로 틀린 숫자가 통과하는 같은 종류). 가짜 LLM — 녹화 아님.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from tests.conftest import EXAMPLES, FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

CASE = load_json(EXAMPLES / "ask_request.json")["case_no"]
OTHER = "CASE-2022-000058" if CASE != "CASE-2022-000058" else "CASE-2022-000059"


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _facts(name: str = "facts_ask_mixed.json") -> Facts:
    return Facts.model_validate(load_json(FIXTURES / name))


def _ask(question: str, answer: str, cites: list[str], facts: Facts | None = None):
    llm = StubLlm(responses=[plan_text("FACT", None, ["flows"]), answer_text(answer=answer, cites=cites)])
    svc, repo = build_service(llm, facts=facts or _facts())
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN")), llm, repo


def _unverified(res) -> None:  # noqa: ANN001
    assert (res.status, res.answer, res.cites, res.evidence_ids) == (AskStatus.UNVERIFIED, None, [], [])


# ---------- H6 다른 케이스 ----------


def test_h6_question_naming_other_case_ends_before_plan() -> None:
    llm = StubLlm(responses=[])  # 부르면 IndexError
    svc, repo = build_service(llm, facts=_facts())
    res = svc.ask(ask_request(f"{OTHER}의 입금 합계는?", rule_id="R02_FAN_IN"))
    assert (res.status, res.out_of_scope_reason.value, res.evidence_ids) == (
        AskStatus.OUT_OF_SCOPE,
        "OUTSIDE_CASE",
        [],
    )
    assert llm.calls == [] and repo.saved[0]["response_payload"]["plan"]["source"] == "code"


def test_h6_question_naming_own_case_goes_to_plan() -> None:
    res, llm, _ = _ask(f"{CASE}의 입금 합계는?", "입금 합계는 27250.50 USD예요.", ["inbound.amount.USD"])
    assert res.status is AskStatus.ANSWERED and len(llm.calls) == 2


def test_h6_answer_naming_other_case_is_unverified() -> None:
    res, _, _ = _ask("입금 합계는?", f"{OTHER}의 입금 합계는 27250.50 USD예요.", ["inbound.amount.USD"])
    _unverified(res)
    (ev,) = [c for c in res.code_checks if c.check.value == "EVIDENCE_IN_SCOPE"]
    assert (ev.match, ev.reason.value, ev.draft_value) == (False, "OUT_OF_SCOPE", "다른 케이스 번호 1개")


# ---------- H1 최대·최소 표시가 있으면 방향 합계로 안 봄 ----------


def test_h1_largest_outbound_is_not_outbound_total() -> None:
    res, _, _ = _ask("가장 큰 출금액은?", "가장 큰 출금액은 24500.25 USD예요.", ["outbound.amount.USD"])
    _unverified(res)


@pytest.mark.parametrize(("side", "status"), [("출금", AskStatus.UNVERIFIED), ("입금", AskStatus.ANSWERED)])
def test_h1_both_extremes_needs_that_side_currency(side: str, status: AskStatus) -> None:
    """multi_currency 는 입금만(EUR 1건) — `출금의 최대와 최소는 모두 9800.25 EUR` 는 출금 EUR 없음 → UNVERIFIED."""
    cites = ["amount_range.EUR.max", "amount_range.EUR.min"]
    res, _, _ = _ask(
        "범위는?", f"{side}의 최대와 최소는 모두 9800.25 EUR예요.", cites, _facts("facts_multi_currency.json")
    )
    assert res.status is status


# ---------- H2 나열 이어받기는 같은 문장 안에서만 ----------


def test_h2_list_inherit_does_not_cross_sentence() -> None:
    res, _, _ = _ask(
        "입금은?", "입금 합계는 27250.50 USD예요. 27250.50 USD를 한 번에 받았어요.", ["inbound.amount.USD"]
    )
    _unverified(res)


def test_h2_list_in_same_sentence_still_inherits() -> None:
    facts = _facts("facts_multi_currency.json")
    res, _, _ = _ask("합계는?", "들어온 돈의 통화별 합계는 9800.25 EUR, 42750.50 USD예요.",
                     ["inbound.amount.EUR", "inbound.amount.USD"], facts)  # fmt: skip
    assert res.status is AskStatus.ANSWERED
