"""SCRUM-228 — 슬롯 생성기·표기 도우미 (docs/str/05 narrative_v4 "슬롯 생성기")."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import masking
from aml_ai.str.domain.display_format import (
    ko_date,
    ko_datetime,
    label_with_code,
    money,
    obs_value,
    topic,
    with_ro,
)
from aml_ai.str.domain.display_slots import build_slots
from aml_ai.str.domain.fact_keys import fact_keys
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.v4_slot_support import facts_sources, load_fixture

LABELS = load_display_labels()


def _texts(name: str) -> dict[SectionV2, list[str]]:
    slots = build_slots(masking.mask_for_llm(load_fixture(name)), LABELS)
    return {sec: [s.text for s in sents] for sec, sents in slots.items()}


def test_money_only_adds_commas() -> None:
    assert money("42750.50") == "42,750.50"
    assert money("0.004200") == "0.004200"
    assert money("320000000.00") == "320,000,000.00"


def test_dates_keep_seconds_only_when_nonzero() -> None:
    assert ko_date(date(2021, 3, 14)) == "2021년 3월 14일"
    assert ko_datetime(datetime(2022, 9, 2, 0, 14)) == "2022년 9월 2일 00:14"
    assert ko_datetime(datetime(2022, 9, 4, 22, 51, 30)) == "2022년 9월 4일 22:51:30"


def test_obs_value_no_rounding() -> None:
    assert obs_value(3.0) == "3"
    assert obs_value(0.75) == "0.75"


def test_label_with_code_skips_same_text() -> None:
    """표기가 원문과 같으면 괄호 병기 생략 — `ACH(ACH)` 안 씀(★B 1)."""
    assert label_with_code("ACH", "ACH") == "ACH"
    assert label_with_code("전신환", "Wire") == "전신환(Wire)"


def test_particles() -> None:
    assert topic("업종") == "업종은" and topic("고객 정보") == "고객 정보는"
    assert (
        with_ro("낮음") == "낮음으로"
        and with_ro("투자") == "투자로"
        and with_ro("사업 대금 결제") == "사업 대금 결제로"
    )


def test_fan_in_slots_exact() -> None:
    t = _texts("facts_fan_in.json")
    assert t[SectionV2.SUBJECT] == [
        "보고 대상자는 Sole Proprietorship #50438(개인사업자)임.",
        "업종은 소매업임.",
        "고객 위험등급은 '낮음'으로 분류되어 있음.",
        "계좌 목적은 매출 대금 수납으로 등록되어 있음.",
        "고객 등록일은 2021년 3월 14일임.",  # SCRUM-269 ③-1
        "과거 경보 이력은 1건임.",
    ]
    assert t[SectionV2.DATE] == [
        "거래 기간은 2022년 9월 2일 00:14부터 2022년 9월 2일 22:51까지임.",
        "거래는 모두 같은 날 이루어짐.",
    ]
    assert t[SectionV2.PLACE][1:] == [
        "상대 계좌는 3개임.",
        "이 가운데 타행 계좌는 3개임.",
    ]  # 영업점 삭제·0 생략(SCRUM-265 2/2)
    assert t[SectionV2.INSTRUMENT] == [
        "내부 거래를 뺀 입금·출금의 결제 방식은 ACH 3건임.",
        "내부 거래를 뺀 입금·출금의 거래 통화는 미국 달러(USD)임.",
    ]
    assert t[SectionV2.METHOD][:4] == [
        "자금 집중(FAN_IN) 유형으로 분류됨.",
        "입금은 3건, 출금은 0건, 내부 거래는 0건임.",
        "입금 합계는 42,750.50 미국 달러(USD)임.",
        "내부 거래를 뺀 입금·출금의 거래 금액은 최소 12,500.00 미국 달러, 최대 16,250.50 미국 달러임.",
    ]
    assert t[SectionV2.OPINION] == []


@pytest.mark.parametrize(
    ("changes", "present"),
    [({}, True), ({"end": "2022-09-03T00:00:00"}, False)],
)
def test_only_single_day_flag_has_a_slot_sentence(changes: dict, present: bool) -> None:
    """플래그 문장은 single_day 만 — 타행/자행·입금만·출금만은 숫자 문장과 반복이라 없음(05)."""
    masked = masking.mask_for_llm(load_fixture("facts_fan_in.json"))
    masked["period"]["end"] = changes.get("end", masked["period"]["end"])
    slots = build_slots(masked, LABELS)
    texts = [s.text for sents in slots.values() for s in sents]
    assert ("거래는 모두 같은 날 이루어짐." in texts) is present
    assert not any("모두 타행" in t or "모두 자행" in t or "입금만" in t or "출금만" in t for t in texts)


def test_multi_currency_null_and_bitcoin_slots() -> None:
    t = _texts("facts_multi_currency.json")
    assert "업종은 자료 없음." in t[SectionV2.SUBJECT]
    assert "고객 등록일은 자료 없음." in t[SectionV2.SUBJECT]
    assert (
        t[SectionV2.INSTRUMENT]
        == [
            "내부 거래를 뺀 입금·출금의 결제 방식은 ACH 2건, 비트코인(Bitcoin), 전신환(Wire) 1건임.",
            "내부 거래를 뺀 입금·출금의 거래 통화 가운데 대응이 확인된 통화는 유로(EUR), 미국 달러(USD)임.",  # 미등록 있음(SCRUM-265 2/2)
            "Peso Uruguay 통화 거래는 대응 미확인임.",
        ]
    )
    # SCRUM-264: basis null 분기 없음 — 표기는 이름 기준(inflow_ratio_window → 실제 이름, v4_real_names)
    assert "모델 관측값(관측 구간 자료 없음)에서 통화별 최대 수취 금액 비중은 0.75임." in t[SectionV2.GROUNDS]
    # 입금에 미등록 통화 거래가 있음 → 합계 범위(SCRUM-265 2/2 추가 검토 2차)
    assert (
        "입금 가운데 대응이 확인된 통화 거래의 합계는 9,800.25 유로(EUR), 42,750.50 미국 달러(USD)임."
        in t[SectionV2.METHOD]
    )
    assert t[SectionV2.DATE] == ["거래 기간은 2022년 9월 2일 00:14부터 2022년 9월 4일 22:51:30까지임."]


def test_customer_null_one_sentence() -> None:
    _, facts = facts_sources()[0]
    masked = masking.mask_for_llm(facts)
    masked["customer"] = None
    subject = [s.text for s in build_slots(masked, LABELS)[SectionV2.SUBJECT]]
    assert subject[1] == "고객 정보는 자료 없음."


def test_paths_verified_sentences_use_hop_unit() -> None:
    _, facts = facts_sources()[0]
    masked = masking.mask_for_llm(facts)
    masked["paths"] = {"kind": "CYCLE", "count": 2, "max_hops": 3, "max_accounts": 3}
    method = [s.text for s in build_slots(masked, LABELS)[SectionV2.METHOD]]
    assert method[-3:] == [
        "확인된 경로는 2개임.",
        "가장 긴 경로는 3홉임.",
        "경로 하나가 거친 계좌는 최대 3개임.",
    ]


def test_no_observations_and_no_typology() -> None:
    _, facts = facts_sources()[0]
    masked = masking.mask_for_llm(facts)
    masked["observations"], masked["typology"] = [], None
    slots = build_slots(masked, LABELS)
    assert [s.text for s in slots[SectionV2.GROUNDS]] == [
        "점수를 높인 모델 관측값은 제공된 자료로 확인되지 않음."
    ]
    assert not any("유형으로 분류됨" in s.text for s in slots[SectionV2.METHOD])


@pytest.mark.parametrize("source", [s for s, _ in facts_sources()])
def test_slot_cites_are_fact_keys(source: str) -> None:
    facts = dict(facts_sources())[source]
    keys = fact_keys(facts)
    slots = build_slots(masking.mask_for_llm(facts), LABELS)
    assert {c for sents in slots.values() for s in sents for c in s.cites} <= set(keys)
