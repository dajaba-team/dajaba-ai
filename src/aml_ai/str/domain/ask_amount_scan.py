"""질문 답변 금액 위치 — 공용 `find_pairs` 와 같은 순서·같은 쌍 + 통화 표기 위치 (06 "질문 답변" 8번, 추가 검토 3). 순수 함수.

공용 스캔 파일은 고치지 않고(초안 경로 develop 그대로) 같은 규칙을 내부 이름으로 다시 돌려 원문 위치를 얻는다.
`ask_amounts.py` 200줄 때문에 분리.
"""

from __future__ import annotations

import re

from aml_ai.str.domain.verification_amount_scan import (  # 공용 순서 그대로 — 내부 이름을 씀
    AmountPair,
    _iter_currency_matches,
    _pair_for,
    gap_before,
)

_SENTENCE = re.compile(r"(?<!\d)[.!?\n]|[.!?\n](?!\d)")


def located_pairs(text: str) -> list[tuple[int, AmountPair]]:
    """`find_pairs` 와 같은 순서·같은 쌍 + 통화 표기 시작 위치."""
    found: list[tuple[int, AmountPair | str]] = []
    used: list[tuple[int, int]] = []
    for start, end, code, alias in _iter_currency_matches(text):
        direct = _pair_for(text, start, end, code, alias)
        if direct is None:
            found.append((start, code))
        else:
            found.append((start, direct[0]))
            used.append(direct[1])
    out: list[tuple[int, AmountPair]] = []
    for start, item in found:
        if isinstance(item, AmountPair):
            out.append((start, item))
        elif (gap := gap_before(text, start, used)) is not None:
            out.append((start, AmountPair(raw=gap, currency=item, value=None)))
    return out


def segment(text: str, pos: int, located: list[tuple[int, AmountPair]], pair: AmountPair) -> tuple[str, bool]:
    """(같은 문장에서 바로 앞 금액의 통화 표기 뒤부터 이 금액 숫자 앞까지, 같은 문장에 앞 금액이 있었는지).
    마침표·줄바꿈을 지나면 앞 금액이 없는 것으로 — 나열 이어받기가 문장을 넘지 않게(추가 검토 4 H2)."""
    starts = [m.end() for m in _SENTENCE.finditer(text, 0, pos)]
    begin = starts[-1] if starts else 0
    prev = [p for p, _ in located if begin <= p < pos]
    seg = text[(max(prev) if prev else begin) : pos]
    seg = seg[: seg.rfind(pair.raw)] if pair.raw in seg else seg
    if not prev:
        return seg, False
    return re.sub(r"^[A-Z]{3}\b|^[^\s,·]+?(?=[\s,·])", "", seg, count=1), True  # 앞 통화 표기 떼기
