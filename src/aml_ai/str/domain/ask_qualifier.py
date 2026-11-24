"""질문 한정어 ↔ 자리표 집계 범위 (docs/str/06 "질문 답변" 방향 전환, SCRUM-362 추가 검토 3 H2 · ★B8 D-1·D-2 · SCRUM-412). 순수 함수.

facts 는 기간 전체 집계 — 일별·방향별 최대 없음. 기간 조건과 극값 조건은 `ask_checks.qualifier_mismatch` 가 따로 세서 더함.
"""

from __future__ import annotations

import unicodedata

from aml_ai.str.domain.ask_slots import AskSlots
from aml_ai.str.domain.constants_ask_qualifier import (
    ASK_NOT_PERIOD_DERIVED,
    ASK_PERIOD_FREE_KEYS,
    ASK_PERIOD_FREE_PREFIXES,
    RE_DATE_QUALIFIER,
)


def period_mismatch(slots: AskSlots, asked: bool) -> int:
    """기간 전체 집계 자리표 출현 수 중 막을 것(원칙 (A), SCRUM-412 추가 검토 2·3).

    답의 자리표 밖 글에 기간 낱말이 있으면(관측값만 있는 절 안은 빼고) 집계 자리표 전부(질문과 무관). 없고 질문에
    한정어가 있으면(`asked`) 같은 문장에 `period` 가 없거나 거래 기간에서 계산하지 않은 키(P6 꼴만 허용).
    """
    rows = list(zip(slots.spans, slots.sentences, strict=True))
    aggregates = [(key, sent) for (key, _, _), sent in rows if is_period_aggregate(key)]
    if not aggregates:
        return 0
    if _answer_period_words(slots) > _observation_clause_words(slots):
        return len(aggregates)
    if not asked:
        return 0
    period_sentences = {sent for (key, _, _), sent in rows if key == "period"}
    return sum(
        sent not in period_sentences or key.startswith(ASK_NOT_PERIOD_DERIVED) for key, sent in aggregates
    )


def _answer_period_words(slots: AskSlots) -> int:
    return len(RE_DATE_QUALIFIER.findall(unicodedata.normalize("NFKC", slots.outside)))


def _observation_clause_words(slots: AskSlots) -> int:
    """자리표가 `observations.*` 뿐인 절 안의 기간 낱말 수 — 관측값은 자기 창(window)이라 안 셈."""
    clauses: dict[str, bool] = {}
    for key, _, clause in slots.spans:
        clauses[clause] = clauses.get(clause, True) and key.startswith("observations.")
    return sum(
        len(RE_DATE_QUALIFIER.findall(unicodedata.normalize("NFKC", c)))
        for c, only in clauses.items()
        if only
    )


def is_period_aggregate(key: str) -> bool:
    """기간과 무관한 키 허용 목록 밖이면 기간 전체 집계(목록에 없는 새 키도)."""
    return not (key in ASK_PERIOD_FREE_KEYS or key.startswith(ASK_PERIOD_FREE_PREFIXES))


def extreme_mismatch(slots: AskSlots, side: str) -> int:
    """한 방향 최대·최소 질문 — 합계 키 · 반대 방향이 있는 `amount_range`(두 방향 합친 범위)."""
    other_side = "outbound" if side == "inbound" else "inbound"
    other = slots.flow_counts[1 if side == "inbound" else 0]
    ranged = sum(k.startswith("amount_range.") for k in slots.keys)
    totals = sum(k.startswith((f"{side}.amount.", f"{other_side}.amount.")) for k in slots.keys)
    return totals + (ranged if other != 0 else 0)
