"""COUNT_MATCH 거리 계산·방향·결제 방식 helper (SCRUM-60).

분류 자체는 `verification_count_kind.py`. 여기는 공용 헬퍼만 — 숫자 양옆 단어 거리 최근접,
방향 단어 숫자별 최근접(동률 UNPARSED), 결제 방식 매칭.
"""

from __future__ import annotations

from enum import StrEnum

from aml_ai.str.domain.constants import (
    DIRECTION_IN_WORDS,
    DIRECTION_INTERNAL_WORDS,
    DIRECTION_OUT_WORDS,
    PAYMENT_FORMAT_ALIASES,
)


class Direction(StrEnum):
    IN = "IN"
    OUT = "OUT"
    INTERNAL = "INTERNAL"
    NONE = "NONE"


UNPARSED = "UNPARSED"


def nearest_distance(before: str, after: str, words: tuple[str, ...]) -> int | None:
    """숫자 양옆에서 words 중 가장 가까운 단어의 글자 거리(없으면 None)."""
    d_before = _nearest_in_direction(before[::-1], tuple(w[::-1] for w in words))
    d_after = _nearest_in_direction(after, words)
    if d_before is None and d_after is None:
        return None
    if d_before is None:
        return d_after
    if d_after is None:
        return d_before
    return min(d_before, d_after)


def _nearest_in_direction(haystack: str, words: tuple[str, ...]) -> int | None:
    best: int | None = None
    for w in words:
        i = haystack.find(w)
        if i == -1:
            continue
        if best is None or i < best:
            best = i
    return best


def any_word_in(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def payment_format_in(clause: str) -> str | None:
    for fmt, aliases in PAYMENT_FORMAT_ALIASES.items():
        if any(a in clause for a in aliases):
            return fmt
    return None


def direction_for_number(before: str, after: str) -> Direction | str:
    """거래 건수 방향 — 숫자 위치 기준 최근접(동률 UNPARSED). `송금` 은 뺌(★A 3)."""
    d_in = nearest_distance(before, after, DIRECTION_IN_WORDS)
    d_out = nearest_distance(before, after, DIRECTION_OUT_WORDS)
    d_int = nearest_distance(before, after, DIRECTION_INTERNAL_WORDS)
    pairs: list[tuple[int, Direction]] = []
    if d_in is not None:
        pairs.append((d_in, Direction.IN))
    if d_out is not None:
        pairs.append((d_out, Direction.OUT))
    if d_int is not None:
        pairs.append((d_int, Direction.INTERNAL))
    if not pairs:
        return Direction.NONE
    pairs.sort(key=lambda x: x[0])
    if len(pairs) >= 2 and pairs[0][0] == pairs[1][0]:
        return UNPARSED
    return pairs[0][1]
