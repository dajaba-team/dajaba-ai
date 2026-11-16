"""AMOUNT_MATCH 안전망 — 숫자와 통화 표기 사이에 한글 낱말이 끼면 UNPARSED (SCRUM-131 ★A-2).

규칙 정본 docs/str/06 "AMOUNT_MATCH" 안전망 ①~③. 확실히 통화 이름을 꾸미는 낱말일 때만 건다.
`verification_amount_scan.find_pairs` 가 바로 붙은 금액이 없는 통화 표기에만 부른다.
"""

from __future__ import annotations

import re

from aml_ai.str.domain.constants import (
    RE_DATE_DOT,
    RE_DATE_ISO,
    RE_DATE_KO,
    RE_DATE_KO_NOYEAR,
    RE_DATE_SLASH,
)
from aml_ai.str.domain.constants_currency import (
    AMOUNT_GAP_STOP_WORDS,
    AMOUNT_GAP_UNIT_WORDS,
    AMOUNT_GAP_WORD_ENDINGS,
    AMOUNT_GAP_WORD_MAX_CHARS,
    AMOUNT_GAP_WORD_MIN_CHARS,
    AMOUNT_GAP_WORDS_MAX,
    CURRENCY_ALIASES,
)
from aml_ai.str.domain.verification_amount_number import parse_before

# 통화 표기 바로 앞 (공백 + 한글 낱말) 1~2개 + 공백. 공백 문자만(줄바꿈 X). 금액은 여기서 안 읽음.
_WORD = f"[가-힣]{{{AMOUNT_GAP_WORD_MIN_CHARS},{AMOUNT_GAP_WORD_MAX_CHARS}}}"
_TAIL_RE = re.compile(rf"(?: +{_WORD}){{1,{AMOUNT_GAP_WORDS_MAX}}} +$")
_WORD_RE = re.compile(_WORD)
_ALIASES: tuple[str, ...] = tuple(a for aliases in CURRENCY_ALIASES.values() for a in aliases)
# 날짜 span — DATE_MATCH·COUNT_MATCH 와 같은 패턴. 금액 덩이가 날짜 안이면 금액 아님.
_DATE_PATTERNS = (RE_DATE_ISO, RE_DATE_KO, RE_DATE_SLASH, RE_DATE_DOT, RE_DATE_KO_NOYEAR)


def gap_before(text: str, start: int, used: list[tuple[int, int]]) -> str | None:
    """통화 표기(start) 앞 안전망 덩이. 걸리지 않으면 None. used = 이미 다른 통화와 짝지은 숫자 span.

    금액 판정은 기존 파서(`parse_before`) 그대로 — 통화 바로 앞 낱말 1개부터 넓혀 보며 처음 읽히는 곳.
    """
    m = _TAIL_RE.search(text[:start])
    if m is None:
        return None
    words = [(w.start() + m.start(), w.group(0)) for w in _WORD_RE.finditer(m.group(0))]
    for k in range(1, len(words) + 1):
        gap_start = words[-k][0]
        if not _modifies_currency([w for _, w in words[-k:]]):
            continue
        pieces = parse_before(text, gap_start)
        if pieces is None:
            continue
        stop = len(text[:gap_start].rstrip(" "))
        span = (stop - len(pieces.raw), stop)
        if _overlaps(used, span) or _in_date(text, span):
            return None
        return text[span[0] : start].strip()
    return None


def _overlaps(spans: list[tuple[int, int]], span: tuple[int, int]) -> bool:
    return any(not (span[1] <= s or e <= span[0]) for s, e in spans)


def _in_date(text: str, span: tuple[int, int]) -> bool:
    return any(_overlaps([m.span()], span) for pattern in _DATE_PATTERNS for m in pattern.finditer(text))


def _modifies_currency(words: list[str]) -> bool:
    """① 통화 표기 없음 · ② `기준` 아님 · ③ 조사·어미로 안 끝남 · 첫 낱말이 단위 아님.

    관측 단어로 숫자를 빼는 규칙은 없음(추가 검토 3차 — 실제 금액까지 빠져 누락이 다시 열림).
    """
    if any(a in w for w in words for a in _ALIASES):
        return False
    if any(w in AMOUNT_GAP_STOP_WORDS or w.endswith(AMOUNT_GAP_WORD_ENDINGS) for w in words):
        return False
    return not _is_unit_word(words[0])


def _is_unit_word(word: str) -> bool:
    """2글자 이상 단위는 그 낱말로 시작, 1글자 단위는 낱말이 단위 그 자체."""
    return any(word.startswith(u) if len(u) > 1 else word == u for u in AMOUNT_GAP_UNIT_WORDS)


__all__ = ["gap_before"]
