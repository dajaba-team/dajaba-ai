"""슬롯 생성기 — 숫자·날짜·금액·건수·계좌가 들어가는 문장은 전부 코드가 (docs/str/05 narrative_v4 "슬롯 생성기"). 순수.

입력은 마스킹한 facts dict(LLM 이 보는 것과 같음 — UNVERIFIED paths·indirect 는 이미 빠짐)와 표기 사전.
문형은 06 검사기를 지나도록 고른 것 — 못 지나면 검사기가 아니라 여기 문형을 바꾼다.
METHOD·GROUNDS·결제 방식은 `display_slots_method.py`.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain.constants_v4 import FLAG_SLOT_TEXT, FLOW_SCOPE, MAPPED_SCOPE
from aml_ai.str.domain.derived_flags import derive_flags
from aml_ai.str.domain.display_format import copula, ko_date, ko_datetime, label_with_code, with_ro
from aml_ai.str.domain.display_labels_check import Labels
from aml_ai.str.domain.display_slots_method import (
    flow_currencies,
    grounds_slots,
    method_slots,
    payment_parts,
)
from aml_ai.str.domain.grounds_flow import flow_sentence
from aml_ai.str.domain.slot_types import Slots, SlotSentence, no_data, slot
from aml_ai.str.domain.typology_support_text import support_sentence


def build_slots(facts: dict[str, Any], labels: Labels, flags: dict[str, bool] | None = None) -> Slots:
    """섹션별 슬롯 문장. OPINION 은 늘 빈 목록. 플래그 문장은 `single_day` 만(05 — 나머지는 숫자 문장과 반복).
    GROUNDS 맨 앞은 유형 뒷받침 판정 문장(판정 없는 유형이면 없음, SCRUM-265 2/2), 둘째는 뒷받침됨일 때만 흐름 문장(SCRUM-269)."""
    flags = derive_flags(facts) if flags is None else flags
    single_day = [slot(FLAG_SLOT_TEXT["single_day"], "period")] if flags["single_day"] else []
    return {
        SectionV2.SUBJECT: subject_slots(facts, labels),
        SectionV2.DATE: date_slots(facts) + single_day,
        SectionV2.PLACE: place_slots(facts),
        SectionV2.INSTRUMENT: instrument_slots(facts, labels),
        SectionV2.METHOD: method_slots(facts, labels),
        SectionV2.GROUNDS: [s for s in (support_sentence(facts, labels), flow_sentence(facts)) if s]
        + grounds_slots(facts, labels),
        SectionV2.OPINION: [],
    }


def subject_slots(facts: dict[str, Any], labels: Labels) -> list[SlotSentence]:
    subj = facts["subject"]
    name, etype = subj.get("entity_name"), subj.get("entity_type")
    out: list[SlotSentence] = []
    if name is None:
        out.append(no_data("보고 대상자 이름", "subject"))
    elif etype is None:
        out.append(slot(f"보고 대상자는 {copula(name)}.", "subject", "subject.entity_name"))
    else:
        who = f"{name}({labels['entity_type'][etype]})"
        out.append(
            slot(f"보고 대상자는 {copula(who)}.", "subject", "subject.entity_name", "subject.entity_type")
        )
    out += _customer_slots(facts.get("customer"), labels)
    out.append(slot(f"과거 경보 이력은 {facts['prior_alert_count']:,}건임.", "prior_alert_count"))
    return out


def _customer_slots(customer: dict[str, Any] | None, labels: Labels) -> list[SlotSentence]:
    if customer is None:
        return [no_data("고객 정보")]
    industry, risk = customer.get("industry"), customer.get("risk_level")
    purpose, onboarded = customer.get("account_purpose"), customer.get("onboarded_at")
    out: list[SlotSentence] = []
    if industry is None:
        out.append(no_data("업종"))
    else:
        out.append(slot(f"업종은 {copula(labels['industry'][industry])}.", "customer.industry"))
    if risk is None:
        out.append(no_data("고객 위험등급"))
    else:
        lab = labels["risk_level"][risk]
        particle = with_ro(lab)[len(lab) :]
        out.append(slot(f"고객 위험등급은 '{lab}'{particle} 분류되어 있음.", "customer.risk_level"))
    if purpose is None:
        out.append(no_data("계좌 목적"))
    else:
        lab = labels["account_purpose"][purpose]
        out.append(slot(f"계좌 목적은 {with_ro(lab)} 등록되어 있음.", "customer.account_purpose"))
    if onboarded is None:
        out.append(no_data("고객 등록일"))
    else:  # SCRUM-269 ③-1 — onboarded_at 은 고객 등록일(계좌 개설일 아님). 06 DATE 는 `등록일` 을 개설일 용도로 읽음
        day = ko_date(date.fromisoformat(str(onboarded)))
        out.append(slot(f"고객 등록일은 {copula(day)}.", "customer.onboarded_at"))
    return out


def date_slots(facts: dict[str, Any]) -> list[SlotSentence]:
    start = ko_datetime(datetime.fromisoformat(facts["period"]["start"]))
    end = ko_datetime(datetime.fromisoformat(facts["period"]["end"]))
    return [slot(f"거래 기간은 {start}부터 {end}까지임.", "period")]


def place_slots(facts: dict[str, Any]) -> list[SlotSentence]:
    banks = facts["counterparty_banks"]
    same, other = banks["same_bank_accounts"], banks["other_bank_accounts"]
    # 영업점 문장 없음(facts 칸 없음) · 자행·타행은 0 인 쪽 생략, 둘 다 0 이거나 둘 다 있으면 둘 다(SCRUM-265 2/2)
    if same == 0 and other > 0:
        banks_text, cites = (
            f"이 가운데 타행 계좌는 {other:,}개임.",
            ("counterparty_banks.other_bank_accounts",),
        )
    elif other == 0 and same > 0:
        banks_text, cites = f"이 가운데 자행 계좌는 {same:,}개임.", ("counterparty_banks.same_bank_accounts",)
    else:
        banks_text = f"이 가운데 자행 계좌는 {same:,}개, 타행 계좌는 {other:,}개임."
        cites = ("counterparty_banks.same_bank_accounts", "counterparty_banks.other_bank_accounts")
    return [
        slot(f"대상 계좌는 {copula(facts['subject']['account_key'])}.", "subject.account_key"),
        slot(f"상대 계좌는 {facts['counterparties']['count']:,}개임.", "counterparties.count"),
        slot(banks_text, *cites),
    ]


def instrument_slots(facts: dict[str, Any], labels: Labels) -> list[SlotSentence]:
    out: list[SlotSentence] = []
    parts, cites = payment_parts(facts, labels)
    if parts:
        out.append(slot(f"{FLOW_SCOPE} 결제 방식은 {copula(', '.join(parts))}.", *cites))
    currencies = flow_currencies(facts)
    if currencies:
        names = ", ".join(label_with_code(labels["currency"][c], c) for c, _ in currencies)
        keys = [k for _, ks in currencies for k in ks]
        head = (
            f"{FLOW_SCOPE} 거래 통화 가운데 {MAPPED_SCOPE}는"
            if facts.get("unmapped_currencies")
            else (f"{FLOW_SCOPE} 거래 통화는")
        )  # 미등록이 있으면 열거가 전체처럼 읽히지 않게(추가 검토 2차)
        out.append(slot(f"{head} {copula(names)}.", *keys))
    for u in facts.get("unmapped_currencies", []):
        out.append(slot(f"{u['name']} 통화 거래는 대응 미확인임.", f"unmapped_currencies.{u['name']}"))
    return out or [no_data(f"{FLOW_SCOPE} 결제 방식")]  # 내부 거래만 — 집계 범위를 문장에
