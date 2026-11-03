"""SCRUM-59 — DATE_MATCH 공개 API. docs/str/06 DATE_MATCH 줄.

용도 세 가지(TRANSACTION / ONBOARD / OBSERVATION) 로 분류해 facts 와 **쓴 정밀도대로** 비교.
WHAT_WHEN_WHERE(v1) 또는 DATE(v2) 섹션에 거래 날짜가 하나도 없으면 그 섹션 MISSING.
UNPARSED 는 추출 못 한 표현.
"""

from __future__ import annotations

from datetime import datetime

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheck,
    CodeCheckName,
    Facts,
    NarrativeSectionBase,
    SectionV1,
    SectionV2,
)
from aml_ai.str.domain.verification_date_scan import (
    DateMention,
    DatePurpose,
    date_as_datetime,
    scan_dates,
)

_TRANSACTION_SECTIONS = frozenset({SectionV1.WHAT_WHEN_WHERE, SectionV2.DATE})


def date_match(facts: Facts, narrative: list[NarrativeSectionBase]) -> list[CodeCheck]:
    """섹션마다 날짜 표현을 뽑고 용도별로 facts 와 비교. docs/str/06."""
    period_year = facts.period.start.year
    out: list[CodeCheck] = []
    for s in narrative:
        mentions = scan_dates(s.text, period_year)
        transaction_dates_count = 0
        for mention in mentions:
            out.append(_judge_one(facts, s.section, mention))
            if mention.purpose == DatePurpose.TRANSACTION:
                transaction_dates_count += 1
        if s.section in _TRANSACTION_SECTIONS and transaction_dates_count == 0:
            out.append(
                CodeCheck(
                    check=CodeCheckName.DATE_MATCH,
                    section=s.section,
                    draft_value=None,
                    source_value=None,
                    match=False,
                    reason=CheckReason.MISSING,
                )
            )
    return out


def _judge_one(facts: Facts, section, mention: DateMention) -> CodeCheck:
    if mention.purpose == DatePurpose.UNPARSED:
        return _mk(section, mention, source=None, match=False, reason=CheckReason.UNPARSED)
    if mention.purpose == DatePurpose.ONBOARD:
        return _judge_onboard(facts, section, mention)
    if mention.purpose == DatePurpose.OBSERVATION:
        return _judge_observation(facts, section, mention)
    return _judge_transaction(facts, section, mention)


def _judge_onboard(facts, section, mention: DateMention) -> CodeCheck:
    onboarded = facts.customer.onboarded_at if facts.customer is not None else None
    source = f"onboarded_at {onboarded.isoformat()}" if onboarded else "onboarded_at (null)"
    if onboarded is None:
        return _mk(section, mention, source=source, match=False, reason=CheckReason.MISMATCH)
    match = mention.date_ == onboarded
    return _mk(section, mention, source=source, match=match, reason=None if match else CheckReason.MISMATCH)


def _judge_transaction(facts, section, mention: DateMention) -> CodeCheck:
    start, end = facts.period.start, facts.period.end
    source = f"period {start.isoformat()}..{end.isoformat()}"
    if mention.time is None:
        # 날짜만 — period 의 날짜 부분 사이인지.
        match = start.date() <= mention.date_ <= end.date()
    else:
        # 날짜+시각 쌍 — 쓴 정밀도대로 datetime 비교.
        drafted = date_as_datetime(mention.date_, mention.time)
        match = _as_naive(start) <= drafted <= _as_naive(end)
    return _mk(section, mention, source=source, match=match, reason=None if match else CheckReason.MISMATCH)


def _judge_observation(facts, section, mention: DateMention) -> CodeCheck:
    windows = [
        (o.window_start, o.window_end)
        for o in facts.observations
        if o.window_start is not None and o.window_end is not None
    ]
    source = f"observation count={len(windows)}"
    if not windows:
        return _mk(section, mention, source=source, match=False, reason=CheckReason.MISMATCH)
    hit = _find_matching_observation(mention, windows)
    if hit is None:
        return _mk(section, mention, source=source, match=False, reason=CheckReason.MISMATCH)
    s, e = hit
    better_source = f"observation {s.isoformat()}..{e.isoformat()}"
    return _mk(section, mention, source=better_source, match=True, reason=None)


def _find_matching_observation(mention: DateMention, windows: list[tuple[datetime, datetime]]):
    for s, e in windows:
        if _observation_match(mention, s, e):
            return (s, e)
    return None


def _observation_match(mention: DateMention, s: datetime, e: datetime) -> bool:
    """쓴 정밀도대로 — 날짜만 쓰면 s·e 의 날짜 부분, 시각까지 쓰면 datetime 그대로."""
    if mention.time is None:
        return mention.date_ in (s.date(), e.date())
    drafted = date_as_datetime(mention.date_, mention.time)
    s_naive, e_naive = _as_naive(s), _as_naive(e)
    # 초 환원 — mention.time_was_zero_seconds=False 이고 초 없음(0), window 도 분 단위면 매치.
    if mention.time[2] == 0 and not mention.time_was_zero_seconds:
        drafted_minutes = drafted.replace(second=0)
        return drafted_minutes in (s_naive.replace(second=0), e_naive.replace(second=0))
    return drafted in (s_naive, e_naive)


def _as_naive(dt: datetime) -> datetime:
    """시간대가 있으면 UTC 로 환산 뒤 떼기 — facts timestamp 는 naive 가정(04)."""
    if dt.tzinfo is None:
        return dt
    return dt.replace(tzinfo=None)


def _mk(section, mention: DateMention, *, source: str | None, match: bool, reason) -> CodeCheck:
    return CodeCheck(
        check=CodeCheckName.DATE_MATCH,
        section=section,
        draft_value=mention.raw,
        source_value=source,
        match=match,
        reason=reason,
    )
