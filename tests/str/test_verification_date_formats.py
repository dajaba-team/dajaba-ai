"""SCRUM-59 — 날짜·시각 지원 형식 전부(docs/str/06 DATE_MATCH 줄).

ISO·한국어·슬래시·점·연도 없는 월일·시각(HH:MM·HH:MM:SS·오전/오후)·범위 전부 통과시킴.
오탐 막기(날짜 아닌 표현) 와 섹션별 돌림은 `test_verification_date.py`.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import SectionV1
from tests.str.verification_support import date, facts_fan_in


def _only_matches(checks: list) -> list:
    return [c for c in checks if c.match]


def test_korean_full_date_matches() -> None:
    out = date(facts_fan_in(), SectionV1.SUMMARY, "2022년 9월 2일 입금")
    assert len(out) == 1 and out[0].match


def test_month_day_without_year_uses_period_year() -> None:
    """`9월 2일` — 연도 없음 → period.start.year(2022)."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, "9월 2일 입금")
    assert len(out) == 1 and out[0].match


def test_slash_date_matches() -> None:
    out = date(facts_fan_in(), SectionV1.SUMMARY, "2022/09/02 입금")
    assert len(out) == 1 and out[0].match


def test_dot_date_matches() -> None:
    out = date(facts_fan_in(), SectionV1.SUMMARY, "2022.9.2 입금")
    assert len(out) == 1 and out[0].match


def test_date_with_hhmm_time_matches() -> None:
    """`2022-09-02 14:30` — 쌍이 period 안."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "2022-09-02 14:30 입금")
    assert len(out) == 1 and out[0].match


def test_date_with_korean_am_pm_matches() -> None:
    """`2022년 9월 2일 오후 2시 30분` → 14:30 변환."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "2022년 9월 2일 오후 2시 30분 입금")
    assert len(out) == 1 and out[0].match


def test_date_with_nonzero_seconds_matches() -> None:
    """`2022-09-02 00:14:30` — 초 그대로 비교, period 안."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "2022-09-02 00:14:30 입금")
    assert len(out) == 1 and out[0].match


def test_range_without_onboard_both_transaction() -> None:
    """개설 단어 없는 범위 — 두 날짜 모두 거래 날짜."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "2022-09-02부터 2022-09-02까지 47건")
    assert len(_only_matches(out)) == 2
