"""AMOUNT_MATCH — 금액+통화 쌍 ↔ 같은 통화의 inbound/outbound total + amount_range min/max.

규칙 정본 docs/str/06. 순수 함수. 텍스트 → 쌍 추출은 `verification_amount_scan`.
"""

from __future__ import annotations

from decimal import Decimal

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheck,
    CodeCheckName,
    Facts,
    NarrativeSectionBase,
)
from aml_ai.str.domain.verification_amount_scan import AmountPair, find_pairs


def amount_match(facts: Facts, narrative: list[NarrativeSectionBase]) -> list[CodeCheck]:
    out: list[CodeCheck] = []
    for section in narrative:
        for pair in find_pairs(section.text):
            out.append(_judge(facts, section, pair))
    return out


def _judge(facts: Facts, section: NarrativeSectionBase, pair: AmountPair) -> CodeCheck:
    if pair.value is None:
        return _make(section, pair, False, CheckReason.UNPARSED)
    matched = _value_in_facts(facts, pair.currency, pair.value)
    return _make(section, pair, matched, None if matched else CheckReason.MISMATCH)


def _make(
    section: NarrativeSectionBase, pair: AmountPair, matched: bool, reason: CheckReason | None
) -> CodeCheck:
    return CodeCheck(
        check=CodeCheckName.AMOUNT_MATCH,
        section=section.section,
        draft_value=f"{pair.raw} ({pair.currency})",
        source_value=None,
        match=matched,
        reason=reason,
    )


def _value_in_facts(facts: Facts, code: str, value: Decimal) -> bool:
    """같은 통화 inbound·outbound total 정확 일치 또는 amount_range min ≤ v ≤ max.

    통화 자체가 facts 에 없으면(KRW·EUR 등) 늘 False → MISMATCH (환산 금지 규칙, docs/str/04).
    """
    for flow in (facts.inbound, facts.outbound):
        for row in flow.by_currency:
            if row.currency == code and value == Decimal(row.total):
                return True
    for rng in facts.amount_range:
        if rng.currency == code and Decimal(rng.min) <= value <= Decimal(rng.max):
            return True
    return False


__all__ = ["amount_match"]
