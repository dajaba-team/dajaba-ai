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
    entries = _currency_entries(facts, pair.currency)
    if pair.value is None:
        return _make(
            section, pair, _all_or_absent(facts, pair.currency, entries), False, CheckReason.UNPARSED
        )
    hit = next((label for label, lo, hi in entries if lo <= pair.value <= hi), None)
    if hit is not None:
        return _make(section, pair, hit, True, None)
    return _make(section, pair, _all_or_absent(facts, pair.currency, entries), False, CheckReason.MISMATCH)


def _make(
    section: NarrativeSectionBase,
    pair: AmountPair,
    source: str,
    matched: bool,
    reason: CheckReason | None,
) -> CodeCheck:
    return CodeCheck(
        check=CodeCheckName.AMOUNT_MATCH,
        section=section.section,
        draft_value=f"{pair.raw} ({pair.currency})",
        source_value=source,
        match=matched,
        reason=reason,
    )


def _currency_entries(facts: Facts, code: str) -> list[tuple[str, Decimal, Decimal]]:
    """같은 통화 값 (표시, 하한, 상한) — inbound·outbound total 은 정확 일치, amount_range 는 min~max.

    통화 자체가 facts 에 없으면(KRW·EUR 등) 빈 목록 → MISMATCH (환산 금지 규칙, docs/str/04).
    """
    out: list[tuple[str, Decimal, Decimal]] = []
    for name, flow in (("inbound", facts.inbound), ("outbound", facts.outbound)):
        for row in flow.by_currency:
            if row.currency == code:
                out.append((f"{name}.amount.{code}={row.total}", Decimal(row.total), Decimal(row.total)))
    for rng in facts.amount_range:
        if rng.currency == code:
            out.append((f"amount_range.{code}={rng.min}~{rng.max}", Decimal(rng.min), Decimal(rng.max)))
    return out


def _all_or_absent(facts: Facts, code: str, entries: list[tuple[str, Decimal, Decimal]]) -> str:
    """MISMATCH·UNPARSED 의 source_value — 같은 통화 값 전부, 없으면 facts 에 있는 통화 코드."""
    if entries:
        return " · ".join(label for label, _, _ in entries)
    rows = [*facts.inbound.by_currency, *facts.outbound.by_currency, *facts.amount_range]
    codes = "·".join(dict.fromkeys(r.currency for r in rows))
    return f"facts에 {code} 없음 ({codes})" if codes else f"facts에 {code} 없음"


__all__ = ["amount_match"]
