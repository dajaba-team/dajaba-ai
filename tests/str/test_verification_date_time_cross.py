"""SCRUM-59 Codex adversarial 회귀 — 모든 날짜 형식에 붙은 시각 교차 테스트.

여섯 날짜 형식(`YYYY-MM-DD`·`YYYY년 M월 D일`·`M월 D일`·`YYYY/MM/DD`·`YYYY.M.D`·`ISO T`) 각각에
HH:MM·HH:MM:SS·오전/오후 H시 M분·H시 M분 네 시각 조합:
- 기간 안 (`00:14`) → match
- 기간 밖 (`23:30`·`오후 11시 30분`) → MISMATCH (★ 날짜만 보고 넘어가지 않기)
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CheckReason, SectionV1
from tests.str.verification_support import date, facts_fan_in

# ── 기간 안 시각(00:14 ≡ period.start) — 모든 형식에서 match ───────


@pytest.mark.parametrize(
    "text",
    [
        "2022-09-02 00:14 입금",
        "2022-09-02 00:14:00 입금",
        "2022년 9월 2일 00:14 입금",
        "2022년 9월 2일 오전 0시 14분 입금",
        "9월 2일 00:14 입금",
        "9월 2일 오전 0시 14분 입금",
        "2022/09/02 00:14 입금",
        "2022/09/02 00:14:00 입금",
        "2022.9.2 00:14 입금",
        "2022.9.2 오전 0시 14분 입금",
        "2022-09-02T00:14:00 입금",
    ],
)
def test_period_start_time_matches(text: str) -> None:
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, text)
    assert len([c for c in out if c.match]) == 1, [(c.draft_value, c.source_value, c.reason) for c in out]


# ── 기간 밖 시각 — 모든 형식에서 MISMATCH (★ 핵심) ─────────────────


@pytest.mark.parametrize(
    "text",
    [
        "2022-09-02 23:30 입금",
        "2022-09-02 23:30:00 입금",
        "2022년 9월 2일 23:30 입금",
        "2022년 9월 2일 오후 11시 30분 입금",
        "9월 2일 23:30 입금",
        "9월 2일 오후 11시 30분 입금",
        "2022/09/02 23:30 입금",
        "2022/09/02 23:30:00 입금",
        "2022.9.2 23:30 입금",
        "2022.9.2 오후 11시 30분 입금",
        "2022-09-02T23:30:00 입금",
    ],
)
def test_period_end_outside_time_mismatches(text: str) -> None:
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, text)
    bads = [c for c in out if not c.match]
    assert bads, f"기간 밖 시각이 조용히 통과하면 안 됨: {text!r}"
    assert all(c.reason is CheckReason.MISMATCH for c in bads), [(c.draft_value, c.reason) for c in bads]


# ── `시간` (지속시간) 은 시각이 아니다 — 날짜만 match (★ 2차 지적) ──


@pytest.mark.parametrize(
    "text",
    [
        "2022-09-02 24시간 동안 3건 입금",
        "2022-09-02 3시간 뒤 입금",
        "9월 2일 24시간 집중 입금",
        "9월 2일 3시간 뒤 추가",
        "2022년 9월 2일 24시간 기준 관측",
    ],
)
def test_duration_hours_not_consumed_as_time(text: str) -> None:
    """`24시간`·`3시간` — `시간` 은 지속시간, 시각이 아님. 날짜만 match."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, text)
    matches = [c for c in out if c.match]
    assert len(matches) == 1, [(c.draft_value, c.source_value, c.reason) for c in out]
    assert "시간" not in matches[0].draft_value


# ── 날짜 바로 뒤 "오전·오후" (숫자 시각 없이) — UNPARSED (★A 4 유지) ──


@pytest.mark.parametrize(
    "text",
    [
        "9월 2일 오전에 처리",
        "9월 2일 오후에 추가 입금",
        "2022-09-02 오전부터",
    ],
)
def test_am_pm_without_number_is_unparsed(text: str) -> None:
    """`오전`·`오후` 뒤에 숫자 시각이 없으면 시간대 단어로 UNPARSED."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, text)
    assert any(c.reason is CheckReason.UNPARSED for c in out), [(c.draft_value, c.reason) for c in out]


# ── 날짜와 시각 사이 공백 0 — 소비기가 받음 ─────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "9월 2일23:30 입금",  # KO_NOYEAR + 공백 0 + 기간 밖
        "2022/09/02 23:30 입금",  # SLASH + 공백 1 + 기간 밖
    ],
)
def test_whitespace_between_date_and_time_consumed(text: str) -> None:
    """공백 0(KO_NOYEAR) 또는 공백 1(SLASH) — 소비기가 받아서 기간 밖은 MISMATCH."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, text)
    assert any(not c.match and c.reason is CheckReason.MISMATCH for c in out), [
        (c.draft_value, c.source_value, c.reason) for c in out
    ]
