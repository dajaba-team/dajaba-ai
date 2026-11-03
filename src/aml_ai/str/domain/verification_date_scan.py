"""SCRUM-59 — DATE_MATCH scan 공개 API 와 공용 데이터 모양 (docs/str/06).

- `DatePurpose` — 네 용도.
- `DateMention` — 본문에서 뽑은 날짜 하나.
- `scan_dates(text, period_year)` — 섹션 하나에서 날짜·시각 쌍을 뽑고 용도를 정한다.

regex → DateMention 변환은 `verification_date_formats.py`, 용도 분류는 `verification_date_purpose.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from aml_ai.str.domain.constants import (
    RE_DATE_DOT,
    RE_DATE_ISO,
    RE_DATE_KO,
    RE_DATE_KO_NOYEAR,
    RE_DATE_SLASH,
)


class DatePurpose:
    TRANSACTION = "TRANSACTION"
    ONBOARD = "ONBOARD"
    OBSERVATION = "OBSERVATION"
    UNPARSED = "UNPARSED"


@dataclass(frozen=True)
class DateMention:
    """본문에서 뽑은 날짜 하나. `time` 가 None 이면 날짜만, 아니면 날짜+시각 쌍.

    `time_was_zero_seconds` 는 "쓴 정밀도" 비교용: 원문이 `:00` 를 명시했는지 아니면 아예 초가
    없었는지 — 지시서 ★A 3: `00:14:00 == 00:14`, `00:14:30` 은 그대로 비교.
    """

    span: tuple[int, int]
    raw: str
    date_: date
    time: tuple[int, int, int] | None
    time_was_zero_seconds: bool
    purpose: str


def scan_dates(text: str, period_year: int) -> list[DateMention]:
    """본문의 모든 날짜 표현을 뽑고 용도를 정한다. 겹치는 매치는 긴 쪽만 남긴다."""
    from aml_ai.str.domain.verification_date_formats import (
        mention_iso,
        mention_ko,
        mention_ko_noyear,
        mention_ymd,
        mentions_vague,
        mentions_year_month_only,
    )
    from aml_ai.str.domain.verification_date_purpose import assign_purpose

    raw: list[DateMention] = []
    for m in RE_DATE_ISO.finditer(text):
        mention = mention_iso(m, text)
        if mention is not None:
            raw.append(mention)
    for m in RE_DATE_KO.finditer(text):
        mention = mention_ko(m, text)
        if mention is not None:
            raw.append(mention)
    for m in RE_DATE_SLASH.finditer(text):
        mention = mention_ymd(m, text)
        if mention is not None:
            raw.append(mention)
    for m in RE_DATE_DOT.finditer(text):
        mention = mention_ymd(m, text)
        if mention is not None:
            raw.append(mention)
    for m in RE_DATE_KO_NOYEAR.finditer(text):
        mention = mention_ko_noyear(m, text, period_year)
        if mention is not None:
            raw.append(mention)
    raw.extend(mentions_year_month_only(text))
    raw.extend(mentions_vague(text))
    unique = _dedupe_by_span(raw)
    return [assign_purpose(text, m) for m in unique]


def _dedupe_by_span(items: list[DateMention]) -> list[DateMention]:
    """겹치는 매치는 가장 긴(또는 먼저 들어온) 하나만 — span 길이 긴 쪽 우선."""
    items = sorted(items, key=lambda m: (m.span[0], -(m.span[1] - m.span[0])))
    out: list[DateMention] = []
    last_end = -1
    for m in items:
        if m.span[0] >= last_end:
            out.append(m)
            last_end = m.span[1]
    return out


def date_as_datetime(d: date, t: tuple[int, int, int] | None) -> datetime:
    """DateMention 하나를 datetime 으로 — 시각 없으면 00:00:00."""
    if t is None:
        return datetime(d.year, d.month, d.day)
    return datetime(d.year, d.month, d.day, t[0], t[1], t[2])
