"""추가 검토 3(SCRUM-362) 반례 — 고치기 전에 넣어 실패를 확인 (정본 docs/str/04·06·08). LLM 없음(가짜 LLM).

H1 결제 방식 범위(내부 Cash) · H2 질문 한정어 ↔ 집계 범위 · H3 방향 "만"·"없음" 범위(근거 부분집합·법인 매핑 누락) ·
H4·H5 자리표 밖 서술어·수량 허용 목록 · H6 판정 도구 비교 지표(자리표 교환).
"""

from __future__ import annotations

import pytest
from tools import ask_judge_text
from tools import ask_premise_judge as judge

from aml_ai.shared.schemas.str import AskStatus, Facts
from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.domain.ask_scope import AskScope, ask_scope
from aml_ai.str.domain.ask_slots import render
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json
from tests.str.ask_recorded_support import FixedAnswer, facts_for, recorded
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text
from tests.str.facts_support import CASES, build

LABELS = load_display_labels()
S = CASES["subject"]["account_key"]
MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
MULTI = Facts.model_validate(load_json(FIXTURES / "facts_multi_currency.json"))
FAN_IN = Facts.model_validate(load_json(FIXTURES / "facts_ask_fan_in.json"))
GAPS = {i["id"]: i for i in load_json(judge.GAPS_SET)["items"]}


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _row(k: int, src: str, dst: str, fmt: str = "ACH") -> dict:
    return {
        "transaction_id": k,
        "ts": f"2022-09-02T{10 + k:02d}:00:00",
        "from_account_key": src,
        "to_account_key": dst,
        "amount_paid": "100.00",
        "currency_paid": "USD",
        "amount_received": "100.00",
        "currency_received": "USD",
        "payment_format": fmt,
        "is_self_transfer": False,
    }


def _status(
    question: str, answer: str, bundles: list[str], facts: Facts = MIXED, kind: str = "FACT"
) -> AskStatus:
    llm = StubLlm([plan_text(kind, None, bundles), answer_text(True, answer)])
    svc, _ = build_service(llm, facts=facts)
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN")).status


# ---------- H1 결제 방식 — 내부·간접 거래가 있으면 케이스 전체 결제 방식을 확인 못 함 ----------


def test_internal_cash_blocks_payment_formats_absence_claim() -> None:
    rows = [_row(k, S, f"0{20 + k}_A{k:07d}") for k in (1, 2, 3)] + [_row(4, S, "10_S0000002", "Cash")]
    facts = build({"transactions": rows})
    assert facts.internal.count == 1 and facts.payment_formats == ["ACH"]
    answer = "현금 거래는 확인되지 않아요. {{payment_formats|이에요}}."
    assert _status("현금 거래도 있었어?", answer, ["formats"], facts) is AskStatus.UNVERIFIED


# ---------- H2 질문 한정어 ↔ 자리표 집계 범위 ----------


def test_directional_max_with_both_direction_range_is_unverified() -> None:
    assert (
        _status("가장 큰 출금액은 얼마야?", "{{amount_range.USD.max|이에요}}.", ["flows"])
        is AskStatus.UNVERIFIED
    )


def test_day_qualifier_with_whole_period_count_is_unverified() -> None:
    answer = "그날은 {{inbound.count|이}} 확인돼요."
    assert _status("9월 3일에 들어온 거래는 몇 건이야?", answer, ["flows"], MULTI) is AskStatus.UNVERIFIED


def test_inbound_only_case_range_answers_inbound_extremes() -> None:
    """F8 꼴 — 출금 0건이라 두 방향 범위 = 입금 범위."""
    answer = "{{amount_range.USD.max|과}} {{amount_range.USD.min|이}} 있어요."
    assert (
        _status("가장 큰 입금액과 가장 작은 입금액은 얼마야?", answer, ["flows"], MULTI) is AskStatus.ANSWERED
    )


def test_period_slot_allowed_with_date_qualifier() -> None:
    answer = "질문하신 기간의 거래는 없어요. 이 케이스는 {{period|이에요}}."
    assert _status("2023년 1월에 들어온 거래는 몇 건이야?", answer, ["flows"], FAN_IN) is AskStatus.ANSWERED


# ---------- H3 방향 "만"·"없음" — 근거가 경보 전체이고 소유 정보가 있을 때만 ----------

ROWS3 = [_row(1, "020_A0000001", S), _row(2, S, "030_B0000001"), _row(3, S, "10_S0000002")]


def _direction(rows: list[dict], scope: AskScope | None) -> str:
    facts = build({"transactions": rows})
    return render("{{direction}}", extract(facts, "R02_FAN_IN", ["flows"], LABELS, scope=scope), LABELS).text


def test_evidence_subset_never_says_only_or_none() -> None:
    sub = AskScope(whole_alert=False, ownership_known=True)
    assert "만" not in _direction([ROWS3[0]], sub)  # 경보엔 출금·내부도 있음
    assert "없음" not in _direction([ROWS3[2]], sub)


def test_missing_ownership_never_says_only() -> None:
    assert "만" not in _direction([ROWS3[1]], AskScope(whole_alert=True, ownership_known=False))


def test_whole_alert_with_ownership_says_only() -> None:
    assert _direction([ROWS3[0]], AskScope(whole_alert=True, ownership_known=True)) == "거래 방향 대외 입금만"


def test_ask_scope_from_request_and_account_entities() -> None:
    accounts = {S, "020_A0000001", "10_S0000002"}
    mapping = {S: "E-S", "020_A0000001": "E-A"}  # 10_S0000002 매핑 없음
    assert ask_scope([1, 2], [1, 2], accounts, mapping) == AskScope(whole_alert=True, ownership_known=False)
    assert ask_scope([1], [1, 2], accounts, {**mapping, "10_S0000002": "E-S"}) == AskScope(False, True)


# ---------- H4·H5 자리표 밖 서술어·수량 — 허용 목록 ----------


def test_correction_then_misdirected_predicate_is_unverified() -> None:
    answer = "{{outbound.count|이에요}}. {{inbound.amount.USD|을}} 송금했어요."
    assert _status("보낸 돈은 통화별로 합계가 얼마야?", answer, ["flows"], FAN_IN) is AskStatus.UNVERIFIED


@pytest.mark.parametrize(
    "tail",
    [
        "입금 건수는 출금 건수의 두 배예요.",
        "입금이 출금을 넘어요.",
        "입금은 출금에 못 미쳐요.",
        "{{inbound.amount.USD}} 초과예요.",
        "Inbound is more than outbound.",
        "Inbound is higher.",
    ],
)
def test_quantity_and_predicates_outside_allowlist_are_unverified(tail: str) -> None:
    answer = "{{compare.count|이에요}}. " + tail
    assert _status("입금이 출금보다 많아?", answer, ["flows"]) is AskStatus.UNVERIFIED, tail


# ---------- H6 판정 도구 — 비교 자리표 지표를 facts 로 따로 대조 ----------


def test_judge_swapped_compare_slots_is_wrong() -> None:
    it = GAPS["O1"]
    raw = "금액은 {{compare.count|이에요}}. 건수는 {{compare.amount.USD|이에요}}."
    svc, _ = build_service(FixedAnswer(recorded(), raw), facts=facts_for(it))
    res = svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))
    piece = extract(facts_for(it), it["rule_id"], res.generation_meta.bundles, LABELS)
    assert ask_judge_text.comparison_wrong(raw, piece)


def test_date_qualifier_count_with_period_in_same_clause_is_answered() -> None:
    """P6 v5 녹화 꼴 — 집계 기간을 코드 이름표가 같은 절에서 밝힘."""
    answer = "질문하신 기간의 거래는 없어요. 이 케이스에는 {{period}}에 {{inbound.count|이}} 확인돼요."
    assert _status("2023년 1월에 들어온 거래는 몇 건이야?", answer, ["flows"], FAN_IN) is AskStatus.ANSWERED
    answer = "{{period|이에요}}. 그날은 {{inbound.count|이}} 확인돼요."  # 다른 절이면 막힘
    assert _status("9월 3일에 들어온 거래는 몇 건이야?", answer, ["flows"], MULTI) is AskStatus.UNVERIFIED
