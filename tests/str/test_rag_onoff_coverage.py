"""SCRUM-225 — 규칙 12 facts 커버리지 셈 (docs/str/10 「RAG 켬/끔 2차」).

문장은 SCRUM-126 ★L-2 실제 생성본(블라인드 md)에서 가져옴 — "출금은 0건"·"내부거래는 0건" 등.
"""

from __future__ import annotations

import json
from pathlib import Path

from aml_ai.shared.schemas.str import Facts, NarrativeSection, SectionV2
from tests.str.rag_onoff_coverage import fact_coverage

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "facts_fan_in.json"

SUBJECT_FULL = (
    "보고 대상자는 Sole Proprietorship #50438이며 업종은 소매업(RETAIL)임. 고객 위험등급은 LOW이며 "
    "계좌 목적은 매출대금 입금(SALES_DEPOSIT)임. 과거 경보 이력은 1건임."
)
SUBJECT_NO_PURPOSE = "보고 대상자는 Sole Proprietorship #50438이며 업종은 소매업(RETAIL)임. 고객 위험등급은 LOW이며 과거 경보 이력은 1건임."
INSTRUMENT = "결제 방식은 ACH이며 거래 건수는 3건임. 거래 통화는 미국 달러(USD)임."
METHOD_NO_RANGE = "입금은 3건이며 합계는 42750.50 미국 달러(USD)임. 출금은 0건이며 내부거래는 0건임."
METHOD_FULL = (
    "입금은 3건이며 합계는 42,750.50 미국 달러(USD)임. 거래별 금액 범위는 최소 12,500.00 미국 달러(USD)부터 "
    "최대 16250.50 미국 달러(USD)까지임. 출금 거래는 0건이며 내부 거래는 0건임."
)
GROUNDS = "모델 관측값(관측 구간: 2022-09-02T00:00:00~2022-09-03T00:00:00 기준)에서 서로 다른 입금 상대방 수는 3.0으로 관측됨."


def _facts(**over) -> Facts:  # type: ignore[no-untyped-def]
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    d.update(over)
    return Facts.model_validate(d)


def _n(subject: str, method: str, grounds: str = GROUNDS) -> list[NarrativeSection]:
    texts = {"SUBJECT": subject, "INSTRUMENT": INSTRUMENT, "METHOD": method, "GROUNDS": grounds}
    return [NarrativeSection(section=SectionV2(k), text=v, cites=[]) for k, v in texts.items()]


def test_full_coverage_with_commas_and_spaced_zero_counts() -> None:
    cov = fact_coverage(_n(SUBJECT_FULL, METHOD_FULL), _facts())
    assert cov == {"covered": 14, "required": 14, "missing": []}


def test_126_style_missing_purpose_and_range() -> None:
    cov = fact_coverage(_n(SUBJECT_NO_PURPOSE, METHOD_NO_RANGE), _facts())
    assert cov["required"] == 14
    assert cov["covered"] == 11
    assert sorted(cov["missing"]) == [
        "amount_range.USD.max",
        "amount_range.USD.min",
        "customer.account_purpose",
    ]


def test_wrong_count_is_not_covered() -> None:
    method = METHOD_FULL.replace("출금 거래는 0건", "출금 거래는 2건")
    assert "outbound.count" in fact_coverage(_n(SUBJECT_FULL, method), _facts())["missing"]


def test_null_customer_and_empty_observations_leave_denominator() -> None:
    cov = fact_coverage(
        _n(SUBJECT_FULL, METHOD_FULL, grounds="자료 없음"),
        _facts(customer=None, observations=[], model_signals=[]),
    )
    assert cov["required"] == 14 - 3 - 2
    assert cov["missing"] == []


def test_null_purpose_only_drops_that_item() -> None:
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    d["customer"]["account_purpose"] = None
    cov = fact_coverage(_n(SUBJECT_NO_PURPOSE, METHOD_FULL), Facts.model_validate(d))
    assert cov == {"covered": 13, "required": 13, "missing": []}


def test_observation_window_needs_both_dates() -> None:
    grounds = "모델 관측값(관측 구간: 2022-09-02 기준) 입금 상대방 수는 3으로 관측됨."
    assert fact_coverage(_n(SUBJECT_FULL, METHOD_FULL, grounds), _facts())["missing"] == [
        "observations.account_in_counterparties_24h.window"
    ]


def test_count_before_direction_word_is_covered() -> None:
    """126 case_4 실제 문장 — 숫자가 방향 낱말 앞."""
    method = METHOD_FULL.replace("입금은 3건이며", "상대방 3곳으로부터 3건이 입금된 것으로 파악됨. 입금")
    assert "inbound.count" not in fact_coverage(_n(SUBJECT_FULL, method), _facts())["missing"]


def test_counts_on_both_sides_do_not_mix() -> None:
    """ "출금 0건이며 입금 3건" — 입금 3·출금 0 은 세고, 방향을 바꾼 facts(입금 0·출금 3)로는 안 셈."""
    method = "출금 0건이며 입금 3건임. 합계 42750.50 USD, 범위 12500.00~16250.50 USD. 내부 거래는 0건임."
    ok = fact_coverage(_n(SUBJECT_FULL, method), _facts())["missing"]
    assert "inbound.count" not in ok and "outbound.count" not in ok
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    d["inbound"], d["outbound"] = d["outbound"], d["inbound"]
    swapped = fact_coverage(_n(SUBJECT_FULL, method), Facts.model_validate(d))["missing"]
    assert "inbound.count" in swapped and "outbound.count" in swapped


# 126 ★L-2 case_5_scatter_gather 실제 생성본(A) — 픽스처 facts_scatter_gather.json
SG_FIXTURE = FIXTURE.parent / "facts_scatter_gather.json"
SG_TEXTS = {
    "SUBJECT": "보고 대상자는 Sole Proprietorship #50438이며 엔티티 유형은 개인사업자(SOLE_PROPRIETORSHIP), "
    "업종은 소매업(RETAIL)임. 고객 위험등급은 LOW이며 과거 경보 이력은 1건임.",
    "DATE": "거래 기간은 2022-09-02T00:14:00부터 2022-09-02T22:51:00까지임.",
    "INSTRUMENT": "결제 방식은 ACH이며 거래 건수는 3건임. 거래 통화는 미국 달러(USD)임.",
    "METHOD": "거래 방향은 입금(INBOUND)이며 상대방 3곳으로부터 입금 3건, 합계 42750.50 미국 달러(USD)가 "
    "확인됨. 출금은 0건이며 내부 거래는 0건임.",
    "GROUNDS": "모델 관측값(관측 구간: 2022-09-02T00:00:00~2022-09-02T02:00:00 기준)으로 "
    "inflow_outflow_ratio_2h가 1.0으로 제시됨. 해당 항목은 모델이 주목한 항목이나 기준값은 자료 없음.",
}
OBS_KEYS = ["observations.inflow_outflow_ratio_2h", "observations.inflow_outflow_ratio_2h.window"]


def _sg(grounds: str) -> list[NarrativeSection]:
    texts = {**SG_TEXTS, "GROUNDS": grounds}
    return [NarrativeSection(section=SectionV2(k), text=v, cites=[]) for k, v in texts.items()]


def test_observations_counted_only_in_grounds() -> None:
    """추가 검토 1차 — GROUNDS 를 비우면 DATE 의 거래 날짜·다른 섹션 숫자가 관측값을 가리지 않음."""
    facts = Facts.model_validate(json.loads(SG_FIXTURE.read_text(encoding="utf-8")))
    kept = fact_coverage(_sg(SG_TEXTS["GROUNDS"]), facts)["missing"]
    assert not set(OBS_KEYS) & set(kept)
    dropped = fact_coverage(_sg("자료 없음"), facts)["missing"]
    assert set(OBS_KEYS) <= set(dropped)
