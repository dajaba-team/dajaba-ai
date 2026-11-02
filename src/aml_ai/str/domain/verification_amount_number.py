"""금액 숫자 덩이 파싱 — 통화 바로 앞/뒤 (SCRUM-58).

규칙 정본 docs/str/06. `verification_amount_scan.find_pairs` 가 통화 매치마다 호출.
보조(근사·수사·합산)는 `verification_amount_grammar`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from aml_ai.str.domain.constants import (
    KOREAN_UNIT_MULTIPLIER,
    NON_AMOUNT_TRAILERS,
    RE_AMOUNT_NUMBER,
    UNSUPPORTED_AMOUNT_UNITS,
)
from aml_ai.str.domain.verification_amount_grammar import (
    approx_after,
    approx_before,
    classify_adjacent,
    combine,
    non_amount_trailer_after,
    to_decimal,
    token_boundary_broken,
)

_NUM = f"(?:{RE_AMOUNT_NUMBER.pattern})"
_UNIT_RE = re.compile(r"(?:" + "|".join(KOREAN_UNIT_MULTIPLIER) + r")")


@dataclass(frozen=True)
class AmountPieces:
    raw: str
    value: Decimal | None
    unparsed: bool


def parse_before(text: str, cur_start: int) -> AmountPieces | None:
    """통화 바로 앞의 금액. 공백만 허용, 다른 글자 끼면 결과 없음."""
    end = cur_start
    while end > 0 and text[end - 1] == " ":
        end -= 1
    m = _match_unsupported_before(text, end)
    if m is not None:
        return _unparsed(m.group(0))
    if not _has_number_or_unit_at_end(text, end):
        return _unparsed_or_none_before(text, end)
    chunks, raw_start = _scan_chunks_backward(text, end)
    if not chunks:
        return _unparsed_or_none_before(text, end)
    return _finalize_before(text, raw_start, end, chunks)


def parse_after(text: str, cur_end: int) -> AmountPieces | None:
    """통화 바로 뒤의 금액(앞쪽 영문 형태). 영문 표기 전용.

    아라비아 숫자가 바로 안 붙어 있어도 **근사·한글 수사 금액 모양**이면 UNPARSED — 통화 위치만
    바꿔 UNPARSED 를 우회하지 못하게 (Codex adversarial [high]).
    """
    start = cur_end
    while start < len(text) and text[start] == " ":
        start += 1
    num_m = re.match(_NUM, text[start:])
    if num_m is None:
        raw = classify_adjacent(text, start, "after")
        return _unparsed(raw) if raw else None
    num_end = start + num_m.end()
    verdict = _classify_after_number(text, start, num_end)
    if verdict is not None:
        return None if verdict == "skip" else verdict
    chunks, chunk_end = _scan_chunks_forward(text, num_m.group(0), num_end)
    if approx_after(text, chunk_end):
        return _unparsed(text[start:chunk_end])
    value = combine(chunks)
    raw = text[start:chunk_end]
    return _unparsed(raw) if value is None else AmountPieces(raw=raw, value=value, unparsed=False)


# ---------- 앞쪽 보조 ----------


def _match_unsupported_before(text: str, end: int):
    for unit in UNSUPPORTED_AMOUNT_UNITS:
        m = re.search(_NUM + re.escape(unit) + r"\s*$", text[:end])
        if m:
            return m
    return None


_NUM_OR_UNIT_AT_END = re.compile(rf"(?:{_NUM}|{_UNIT_RE.pattern})\s*$")


def _has_number_or_unit_at_end(text: str, end: int) -> bool:
    return bool(_NUM_OR_UNIT_AT_END.search(text[:end]))


def _scan_chunks_backward(text: str, end: int) -> tuple[list[tuple[Decimal, str | None]], int]:
    chunks: list[tuple[Decimal, str | None]] = []
    cursor = end
    raw_start = end
    while cursor > 0:
        unit_m = re.search(r"(" + _UNIT_RE.pattern + r")\s*$", text[:cursor])
        if unit_m is None:
            num_m = re.search(_NUM + r"\s*$", text[:cursor])
            if num_m is None:
                break
            chunks.append((to_decimal(num_m.group(0)), None))
            raw_start = num_m.start()
            break
        unit = unit_m.group(1)
        num_m = re.search(_NUM + r"\s*(?=" + re.escape(unit) + r"\s*$)", text[:cursor])
        if num_m is None:
            return [], cursor
        chunks.append((to_decimal(num_m.group(0)), unit))
        raw_start = num_m.start()
        cursor = num_m.start()
        while cursor > 0 and text[cursor - 1] == " ":
            cursor -= 1
    return chunks, raw_start


def _finalize_before(
    text: str, raw_start: int, end: int, chunks: list[tuple[Decimal, str | None]]
) -> AmountPieces | None:
    raw_text = text[raw_start:end].strip()
    if token_boundary_broken(text, raw_start, "before"):
        return _unparsed(raw_text)
    if approx_before(text, raw_start):
        return _unparsed(raw_text)
    if non_amount_trailer_after(text, end):
        return None
    value = combine(chunks)
    if value is None:
        return _unparsed(raw_text)
    return AmountPieces(raw=raw_text, value=value, unparsed=False)


# ---------- 뒤쪽 보조 ----------


def _classify_after_number(text: str, start: int, num_end: int) -> AmountPieces | str | None:
    """숫자 바로 뒤 — UNPARSED(AmountPieces), 결과 없음("skip"), 통과(None).

    지원 단위(`억`·`천만`·`만`) 가 먼저 걸리면 `_scan_chunks_forward` 가 처리하도록 None.
    "3천만" 의 `천` 이 미지원으로 가로채지 않게 (Codex adversarial [medium]).
    """
    after = text[num_end:]
    if any(after.startswith(u) for u in KOREAN_UNIT_MULTIPLIER):
        return None
    for unit in UNSUPPORTED_AMOUNT_UNITS:
        if after.startswith(unit):
            return _unparsed(text[start : num_end + len(unit)])
    if token_boundary_broken(text, num_end, "after"):
        return _unparsed(text[start:num_end])
    if any(after.startswith(t) for t in NON_AMOUNT_TRAILERS):
        return "skip"
    if after[:1] in {"-", "/"} and after[1:2].isdigit():
        return "skip"
    return None


_UNIT_FORWARD = re.compile(rf"\s*({_UNIT_RE.pattern})")
_NUM_FORWARD = re.compile(rf"\s*({_NUM})")


def _scan_chunks_forward(
    text: str, first_num: str, num_end: int
) -> tuple[list[tuple[Decimal, str | None]], int]:
    chunks: list[tuple[Decimal, str | None]] = [(to_decimal(first_num), None)]
    cursor = num_end
    while cursor < len(text):
        unit_m = _UNIT_FORWARD.match(text, cursor)
        if unit_m is None or not any(unit_m.group(1) == u for u in KOREAN_UNIT_MULTIPLIER):
            break
        chunks[-1] = (chunks[-1][0], unit_m.group(1))
        num_m = _NUM_FORWARD.match(text, unit_m.end())
        if num_m is None:
            cursor = unit_m.end()
            break
        chunks.append((to_decimal(num_m.group(1)), None))
        cursor = num_m.end()
    return chunks, cursor


def _unparsed(raw: str) -> AmountPieces:
    return AmountPieces(raw=raw, value=None, unparsed=True)


def _unparsed_or_none_before(text: str, end: int) -> AmountPieces | None:
    """통화 바로 앞에 숫자 없을 때 — 근사·한글 수사 금액 모양이면 UNPARSED (매치된 raw 그대로)."""
    raw = classify_adjacent(text, end, "before")
    return _unparsed(raw) if raw else None
