"""질문 한정어 ↔ 자리표 집계 범위 (docs/str/06 "질문 답변" 방향 전환, SCRUM-362 추가 검토 3 H2 · ★B8 D-1·D-2). 순수 함수.

facts 는 기간 전체 집계 — 일별·방향별 최대 없음. 기간 조건과 극값 조건은 `ask_checks.qualifier_mismatch` 가 따로 세서 더함.
"""

from __future__ import annotations

import unicodedata

from aml_ai.str.domain.ask_slots import AskSlots
from aml_ai.str.domain.constants_ask import ASK_PERIOD_AGG_PREFIXES, RE_DATE_QUALIFIER


def period_mismatch(slots: AskSlots) -> int:
    """기간 전체 집계 자리표 출현 중, 같은 문장에 `period` 가 없거나 그 절에 기간 낱말이 있는 것(P6 꼴만 허용)."""
    rows = list(zip(slots.spans, slots.sentences, strict=True))
    period_sentences = {sent for (key, _, _), sent in rows if key == "period"}
    return sum(
        key.startswith(ASK_PERIOD_AGG_PREFIXES)
        and (
            sent not in period_sentences
            or RE_DATE_QUALIFIER.search(unicodedata.normalize("NFKC", clause)) is not None
        )
        for (key, _, clause), sent in rows
    )


def extreme_mismatch(slots: AskSlots, side: str) -> int:
    """한 방향 최대·최소 질문 — 합계 키 · 반대 방향이 있는 `amount_range`(두 방향 합친 범위)."""
    other_side = "outbound" if side == "inbound" else "inbound"
    other = slots.flow_counts[1 if side == "inbound" else 0]
    ranged = sum(k.startswith("amount_range.") for k in slots.keys)
    totals = sum(k.startswith((f"{side}.amount.", f"{other_side}.amount.")) for k in slots.keys)
    return totals + (ranged if other != 0 else 0)
