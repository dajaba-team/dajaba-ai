"""추가 검토 2(SCRUM-362) 반례 — 답 경로. 검토가 재현한 거래 행·답 원문 그대로, 고치기 전에 넣어 실패 확인 (정본 docs/str/04·06).

H1 방향 "만" 범위 · H2 자리표 밖 수량 · H3 0건 정정은 정정 절에만 · H4 말고·양방향 · H5 지표에 은행 구분·통화 · M2 기준값.
LLM 없음(가짜 LLM). 판정 도구 반례는 `test_ask_review_362_2b.py`.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.domain.ask_checks import run
from aml_ai.str.domain.ask_scope import AskScope
from aml_ai.str.domain.ask_slots import render
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text
from tests.str.facts_support import CASES, build

LABELS = load_display_labels()
WHOLE = AskScope(whole_alert=True, ownership_known=True)  # 범위 확인됨(추가 검토 3 H3)
S = CASES["subject"]["account_key"]
MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
FAN_IN = Facts.model_validate(load_json(FIXTURES / "facts_ask_fan_in.json"))
PATHS = Facts.model_validate(load_json(FIXTURES / "facts_ask_paths.json"))
CB = "counterparties_by_direction"


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _row(k: int, src: str, dst: str, cur: str = "USD") -> dict:
    return {
        "transaction_id": k,
        "ts": f"2022-09-02T{10 + k:02d}:00:00",
        "from_account_key": src,
        "to_account_key": dst,
        "amount_paid": "100.00",
        "currency_paid": cur,
        "amount_received": "100.00",
        "currency_received": cur,
        "payment_format": "ACH",
        "is_self_transfer": False,
    }


def _status(question: str, answer: str, bundles: list[str], facts: Facts = MIXED) -> AskStatus:
    llm = StubLlm([plan_text("FACT", None, bundles), answer_text(True, answer)])
    svc, _ = build_service(llm, facts=facts)
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN")).status


# ---------- H1 방향 "만" — 범위를 이름표에, 배타성이 조각으로 확인될 때만 ----------


def test_inbound_with_internal_is_external_inbound_only() -> None:
    """입금 1 · 출금 0 · 내부 1 — "입금만" 이 아니라 대외 거래 범위를 밝힘."""
    facts = build({"transactions": [_row(1, "020_A0000001", S), _row(2, "10_S0000002", S)]})
    assert facts.internal.count == 1
    text = render("{{direction}}", extract(facts, "R02_FAN_IN", ["flows"], LABELS, scope=WHOLE), LABELS).text
    assert text == "거래 방향 대외 입금만"


def test_indirect_only_is_no_external_flow_not_internal_only() -> None:
    """간접 거래만 1건 — 내부 거래 0 인데 "내부 거래만" 이라 하지 않음."""
    facts = build({"transactions": [_row(1, "020_A0000001", "030_B0000001")]})
    assert (facts.inbound.count, facts.outbound.count, facts.internal.count) == (0, 0, 0)
    text = render("{{direction}}", extract(facts, "R02_FAN_IN", ["flows"], LABELS, scope=WHOLE), LABELS).text
    assert text == "거래 방향 대외 입출금 없음"


# ---------- H2 자리표 밖 수량 ----------

PIECE = extract(MIXED, "R02_FAN_IN", ["flows", "counterparties"], LABELS)


def _outside(tail: str):
    (c,) = run(render("{{inbound.count|이에요}}. " + tail, PIECE, LABELS), "입금 거래는?", "CASE-2022-000057")
    return c


@pytest.mark.parametrize(
    "tail",
    [
        "첫 번째 거래는 현금이에요.",
        "두세 건이에요.",
        "삼분의 일이에요.",
        "오십 퍼센트예요.",
        "seven transactions.",
        "수만 건이에요.",
    ],
)
def test_ordinal_range_fraction_percent_english_are_outside_numbers(tail: str) -> None:
    c = _outside(tail)
    assert not c.match and c.draft_value.startswith("자리표 밖 숫자"), tail


def test_su_man_as_particle_is_not_a_number() -> None:
    assert _outside("거래 수만 확인할 수 있어요.").match


# ---------- H3 0건 정정은 정정 절에만 ----------


def test_zero_key_after_misdirected_value_does_not_release() -> None:
    answer = "{{inbound.amount.USD|을}} 출금했어요. {{outbound.count|이에요}}."
    assert _status("보낸 돈은 통화별로 합계가 얼마야?", answer, ["flows"], FAN_IN) is AskStatus.UNVERIFIED


def test_p4_correction_first_still_passes() -> None:
    answer = "질문하신 출금 방향의 거래는 없어요. 이 케이스에는 {{outbound.count|이}} 확인되며, {{inbound.amount.USD|이}} 확인돼요."
    assert _status("보낸 돈은 통화별로 합계가 얼마야?", answer, ["flows"], FAN_IN) is AskStatus.ANSWERED


# ---------- H4 말고·양방향 ----------


def test_excluded_direction_is_not_the_asked_one() -> None:
    assert (
        _status("출금 말고 입금만 몇 건이야?", "{{outbound.count|이에요}}.", ["flows"])
        is AskStatus.UNVERIFIED
    )


def test_two_direction_question_with_one_side_only_is_unverified() -> None:
    assert (
        _status("입금과 출금은 각각 몇 건이야?", "{{outbound.count|이에요}}.", ["flows"])
        is AskStatus.UNVERIFIED
    )


def test_reversed_comparison_needs_code_rendered_compare() -> None:
    """(B1) 로 막음 — 자리표 밖 비교 꼴(추가 검토 2 H4 · ★B6-1 에서는 xfail 이었음)."""
    answer = "{{inbound.amount.USD|이}} {{outbound.amount.USD}}보다 적어요."
    assert _status("입금이 출금보다 많아?", answer, ["flows"]) is AskStatus.UNVERIFIED


# ---------- H5 지표에 은행 구분·통화 ----------


def test_inbound_same_bank_does_not_cover_outbound_other_bank() -> None:
    answer = (
        "{{"
        + CB
        + ".outbound.other_bank_accounts|이에요}}. {{"
        + CB
        + ".inbound.same_bank_accounts|이에요}}."
    )
    assert _status("입금 상대 중 타행 계좌는 몇 개야?", answer, ["counterparties"]) is AskStatus.UNVERIFIED


def test_other_currency_inbound_does_not_cover_outbound() -> None:
    facts = build({"transactions": [_row(1, "020_A0000001", S, "USD"), _row(2, S, "030_B0000001", "EUR")]})
    answer = "{{outbound.amount.EUR|이에요}}. {{inbound.amount.USD|이에요}}."
    assert _status("입금된 EUR 는 얼마야?", answer, ["flows"], facts) is AskStatus.UNVERIFIED


# ---------- M2 기준값 자리표 ----------


def test_baseline_slot_when_not_null() -> None:
    answer = "모델이 주목한 점: {{observations.inflow_outflow_ratio_2h|이에요}}. {{observations.inflow_outflow_ratio_2h.baseline|이에요}}."
    llm = StubLlm([plan_text("WHY", None, ["score_reasons"]), answer_text(True, answer)])
    svc, _ = build_service(llm, facts=PATHS)
    res = svc.ask(ask_request("평소 기준값은 얼마야?", rule_id="R05_SCATTER_GATHER"))
    assert res.status is AskStatus.ANSWERED and "평소 기준값 0.4" in res.answer


def test_baseline_slot_absent_when_null() -> None:
    piece = extract(FAN_IN, "R02_FAN_IN", ["score_reasons"], LABELS)
    assert "observations.account_in_counterparties_24h.baseline" not in piece.keys
