"""자리표 밖 자유문 허용 목록 — 끝맺음·수량 (docs/str/06 "질문 답변" 방향 전환, SCRUM-362 추가 검토 3). 순수 함수.

블록리스트가 아니라 허용 목록: 절 끝 어절이 목록 안이거나 자리표(`§`)로 끝나야 함. 목록은 v5 녹화 42 가 실제로 쓴 것에서.
"""

from __future__ import annotations

import re
import unicodedata

from aml_ai.str.domain.constants_ask import (
    ASK_ALLOWED_ENDINGS,
    ASK_ALLOWED_PAIRS,
    ASK_COPULA_ENDINGS,
    RE_BLOCKED_QUANTITY,
    SLOT_MARKER,
)


def outside_predicates(marked: str) -> int:
    """자리표 밖 절 끝맺음이 허용 목록 밖인 수 + 막는 수량·경계 낱말 수(06 방향 전환 — 블록리스트가 아니라 허용 목록)."""
    text = unicodedata.normalize("NFKC", marked)
    bad = len(RE_BLOCKED_QUANTITY.findall(text))
    for clause in re.split(r"[.!?\n,]", text):
        words = [w.strip("'\"()·:") for w in clause.split()]
        words = [w for w in words if w]
        if words and not _allowed_end(words):
            bad += 1
    return bad


def _allowed_end(words: list[str]) -> bool:
    last, prev = words[-1], (words[-2] if len(words) > 1 else "")
    return (
        last == SLOT_MARKER
        or last in ASK_ALLOWED_ENDINGS
        or (prev, last) in ASK_ALLOWED_PAIRS
        or last.endswith(ASK_COPULA_ENDINGS)
    )
