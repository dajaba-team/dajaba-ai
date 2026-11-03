"""SCRUM-59 — 날짜 regex 매치 → DateMention 변환. Codex adversarial(2026-11-03) 반영.

잘못된 월·일·시·분 값은 전부 UNPARSED(ValueError 로 verify 멈추지 않음), 모든 지원 날짜 형식에
붙은 시각을 공통 helper(`verification_date_time`) 로 읽어 "날짜만 보고 넘어가는" 오탐 금지.
"""

from __future__ import annotations

import re
from datetime import date

from aml_ai.str.domain.constants import (
    RE_YEAR_MONTH_ONLY,
    TIME_OF_DAY_WORDS,
    VAGUE_DATE_SUFFIXES,
)
from aml_ai.str.domain.verification_date_scan import DateMention, DatePurpose
from aml_ai.str.domain.verification_date_time import consume_trailing_time


def mention_iso(m: re.Match, text: str) -> DateMention | None:
    """RE_DATE_ISO — 자체 시각 그룹(T·공백) 포함, 날짜만이면 뒤 KO 시각 소비."""
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return _unparsed_span(m)
    if m.group(4) is None:
        return _attach_trailing_time(m.span(), m.group(0), d, text)
    hh, mm_ = int(m.group(4)), int(m.group(5))
    ss_raw = m.group(6)
    ss = int(ss_raw) if ss_raw is not None else 0
    had_seconds = ss_raw is not None
    if not (0 <= hh < 24 and 0 <= mm_ < 60 and 0 <= ss < 60):
        return _unparsed_span(m)
    return DateMention(
        span=m.span(),
        raw=m.group(0),
        date_=d,
        time=(hh, mm_, ss),
        time_was_zero_seconds=had_seconds and ss == 0,
        purpose=DatePurpose.TRANSACTION,
    )


def mention_ko(m: re.Match, text: str) -> DateMention | None:
    """RE_DATE_KO — 날짜만 매치. 시각은 공용 소비기(`_attach_trailing_time`)로 소비(초 포함)."""
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return _unparsed_span(m)
    return _attach_trailing_time(m.span(), m.group(0), d, text)


def mention_ymd(m: re.Match, text: str) -> DateMention | None:
    """RE_DATE_SLASH·RE_DATE_DOT — 날짜만 매치. 뒤에 붙은 시각을 `_consume_trailing_time` 로."""
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return _unparsed_span(m)
    return _attach_trailing_time(m.span(), m.group(0), d, text)


def mention_ko_noyear(m: re.Match, text: str, period_year: int) -> DateMention | None:
    """RE_DATE_KO_NOYEAR — 연도 없는 M월 D일 + 뒤 시각 소비.

    시간대 단어(아침 등) UNPARSED 체크는 `_attach_trailing_time` 안에서 공통으로.
    """
    try:
        d = date(period_year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return _unparsed_span(m)
    return _attach_trailing_time(m.span(), m.group(0), d, text)


def _attach_trailing_time(span: tuple[int, int], raw: str, d: date, text: str) -> DateMention:
    """날짜 뒤 시각 토큰 처리. ok→time 포함, unparsed→UNPARSED, none→시간대 단어 체크 후 TRANSACTION."""
    status, new_end, time_tuple, had_zero_seconds = consume_trailing_time(text, span[1])
    if status == "ok":
        return _with_time(span[0], new_end, d, time_tuple, had_zero_seconds, text)
    if status == "unparsed":
        return _unparsed_range(span[0], new_end, d, text)
    return _none_fallback(span, raw, d, text)


def _with_time(
    start: int, new_end: int, d: date, time_tuple, had_zero_seconds: bool, text: str
) -> DateMention:
    return DateMention(
        span=(start, new_end),
        raw=text[start:new_end],
        date_=d,
        time=time_tuple,
        time_was_zero_seconds=had_zero_seconds,
        purpose=DatePurpose.TRANSACTION,
    )


def _unparsed_range(start: int, new_end: int, d: date, text: str) -> DateMention:
    return DateMention(
        span=(start, new_end),
        raw=text[start:new_end],
        date_=d,
        time=None,
        time_was_zero_seconds=False,
        purpose=DatePurpose.UNPARSED,
    )


def _none_fallback(span: tuple[int, int], raw: str, d: date, text: str) -> DateMention:
    """소비기 none — 날짜 바로 뒤 시간대 단어(숫자 시각 없이) 있으면 UNPARSED(★A 4)."""
    tail = text[span[1] : span[1] + 4]
    purpose = (
        DatePurpose.UNPARSED
        if any(tail.lstrip().startswith(w) for w in TIME_OF_DAY_WORDS)
        else DatePurpose.TRANSACTION
    )
    return DateMention(
        span=span,
        raw=raw,
        date_=d,
        time=None,
        time_was_zero_seconds=False,
        purpose=purpose,
    )


def mentions_year_month_only(text: str) -> list[DateMention]:
    """`YYYY년 M월`(일 없음) → UNPARSED. 월 범위는 안 봄 — UNPARSED 는 date 안 씀."""
    return [_unparsed_span(m) for m in RE_YEAR_MONTH_ONLY.finditer(text)]


def mentions_vague(text: str) -> list[DateMention]:
    """`9월 초`·`9월 중순`·`9월 말`·`9월 중` → UNPARSED. 월 범위 안 봄."""
    out: list[DateMention] = []
    pattern = re.compile(r"(\d{1,2})월\s*(" + "|".join(VAGUE_DATE_SUFFIXES) + r")(?![순])")
    for m in pattern.finditer(text):
        out.append(_unparsed_span(m))
    for m in re.finditer(r"(\d{1,2})월\s*중순", text):
        out.append(_unparsed_span(m))
    return out


def _unparsed_span(m: re.Match) -> DateMention:
    """월·일 범위 등 어느 값이 유효하지 않더라도 안전한 sentinel 로 UNPARSED (SCRUM-59 Codex adversarial)."""
    return DateMention(
        span=m.span(),
        raw=m.group(0),
        date_=date(1970, 1, 1),
        time=None,
        time_was_zero_seconds=False,
        purpose=DatePurpose.UNPARSED,
    )
