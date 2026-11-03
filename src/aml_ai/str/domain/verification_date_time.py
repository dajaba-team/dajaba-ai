"""SCRUM-59 — 날짜 뒤에 붙은 시각 조각 소비(공용). docs/str/06 DATE_MATCH 줄.

모든 지원 날짜 형식(ISO·KO·YMD·KO_NOYEAR 등) 뒤에 공백+시각이 올 때 하나의 소비기로 읽는다.
Codex adversarial(2026-11-03) 반영 — 날짜만 보고 조용히 넘어가지 않음, 범위 밖은 UNPARSED.
"""

from __future__ import annotations

import re

_RE_TIME_HHMM = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:])")
# `시` 뒤 `(?!간)` — `24시간`·`3시간` 은 시각이 아니라 지속시간(SCRUM-59 Codex adversarial 2차).
_RE_TIME_KO = re.compile(r"(오전|오후)?\s*(\d{1,2})시(?!간)(?:\s*(\d{1,2})분)?")
# 시각으로 "보이는" 토큰 — regex 매치 실패했을 때 "조용히 none" 으로 떨어지지 않도록 걸러냄
# (SCRUM-59 Codex adversarial 3차: `23:300`·`22:51:300` 처럼 뒤 숫자가 더 붙은 조각).
# `시(?!간)` — `24시간`·`3시간` 지속시간은 시각 모양이 아님(날짜만 통과해야).
_RE_TIME_LOOKS_LIKE = re.compile(r"\d{1,}:\d{1,}|(?:오전|오후)?\s*\d{1,}시(?!간)")
_WHITESPACE = frozenset(" \t\n\r")


def consume_trailing_time(text: str, end: int) -> tuple[str, int, tuple[int, int, int] | None, bool]:
    """날짜 매치 끝 뒤에 바로 붙은 시각 조각 소비 — 공백(space/tab/newline/return) 0 개도 허용.

    status: "ok" (시각 포함) · "unparsed" (시각 모양인데 범위 밖·토큰 깨짐) · "none" (시각 아닌 글)
    """
    j = end
    while j < len(text) and text[j] in _WHITESPACE:
        j += 1
    rest = text[j:]
    m = _RE_TIME_HHMM.match(rest)
    if m:
        return _finish_hhmm(m, j)
    m = _RE_TIME_KO.match(rest)
    if m:
        return _finish_ko_time(m, j)
    # 시각으로 "보이는" 토큰이 있는데 매치 실패 — malformed 로 보고 UNPARSED
    look = _RE_TIME_LOOKS_LIKE.match(rest)
    if look is not None:
        return "unparsed", j + look.end(), None, False
    return "none", end, None, False


def _finish_hhmm(m: re.Match, j: int) -> tuple[str, int, tuple[int, int, int] | None, bool]:
    hh, mm_ = int(m.group(1)), int(m.group(2))
    ss_raw = m.group(3)
    ss = int(ss_raw) if ss_raw is not None else 0
    new_end = j + m.end()
    if not (0 <= hh < 24 and 0 <= mm_ < 60 and 0 <= ss < 60):
        return "unparsed", new_end, None, False
    had_seconds = ss_raw is not None
    return "ok", new_end, (hh, mm_, ss), had_seconds and ss == 0


def _finish_ko_time(m: re.Match, j: int) -> tuple[str, int, tuple[int, int, int] | None, bool]:
    am_pm = m.group(1)
    hh = int(m.group(2))
    mm_ = int(m.group(3)) if m.group(3) is not None else 0
    new_end = j + m.end()
    if am_pm == "오후" and hh != 12:
        hh += 12
    elif am_pm == "오전" and hh == 12:
        hh = 0
    if not (0 <= hh < 24 and 0 <= mm_ < 60):
        return "unparsed", new_end, None, False
    return "ok", new_end, (hh, mm_, 0), False
