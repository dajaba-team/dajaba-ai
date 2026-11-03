"""SCRUM-59 — DATE_MATCH 가 잡는 것(MISMATCH·UNPARSED·MISSING). docs/str/08 "잡아야" 섹션.

주입 3·19·22 포함(검사 함수 직접 호출 방식 — 60 끝에 run_code_checks 로).
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CheckReason, SectionV1, SectionV2
from aml_ai.str.domain import verification
from tests.str.verification_support import (
    date,
    facts_customer_null,
    facts_fan_in,
    section,
)


def _mismatches(checks: list) -> list:
    return [c for c in checks if not c.match]


def _unparseds(checks: list) -> list:
    return [c for c in checks if c.reason is CheckReason.UNPARSED]


# ── 주입 3·19·22 활성 ───────────────────────────────────────────────


def test_injection_3_date_out_of_period_mismatch() -> None:
    """주입 3 — `9월 5일` 기간 밖 → MISMATCH."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "9월 5일 입금")
    assert len(_mismatches(out)) == 1
    assert _mismatches(out)[0].reason is CheckReason.MISMATCH


def test_injection_19_birthday_in_transaction_slot_mismatch() -> None:
    """주입 19 — `2021년 3월 14일에 47건 입금`: 개설 단어 없음 → 거래 날짜 → 기간 밖 → MISMATCH."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "2021년 3월 14일에 47건 입금")
    assert len(_mismatches(out)) == 1
    assert _mismatches(out)[0].reason is CheckReason.MISMATCH


def test_injection_22_range_with_onboard_unparsed() -> None:
    """주입 22 — `2021년 3월 14일과 2022년 9월 2일 사이 개설`: 범위 + 개설 단어 → UNPARSED."""
    out = date(facts_fan_in(), SectionV1.WHO, "2021년 3월 14일과 2022년 9월 2일 사이 개설")
    assert len(_unparseds(out)) >= 1


# ── 거리가 같은 두 날짜 ─────────────────────────────────────────────


def test_equal_distance_two_dates_unparsed() -> None:
    """개설 단어에서 앞뒤 두 날짜까지 글자 거리가 같음 → UNPARSED."""
    out = date(facts_fan_in(), SectionV1.WHO, "2021-03-14 개설 2022-09-02")
    assert len(_unparseds(out)) >= 1


# ── 추측 못 할 날짜 모양 ────────────────────────────────────────────


def test_vague_date_cho_unparsed() -> None:
    """`9월 초` → UNPARSED."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, "9월 초 입금")
    assert len(_unparseds(out)) >= 1


def test_vague_date_mid_unparsed() -> None:
    """`2022년 9월 중순` → UNPARSED."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, "2022년 9월 중순 입금")
    assert len(_unparseds(out)) >= 1


def test_month_only_unparsed() -> None:
    """`2022년 9월` → UNPARSED."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, "2022년 9월 입금 집중")
    assert len(_unparseds(out)) >= 1


def test_date_followed_by_time_of_day_word_unparsed() -> None:
    """`9월 2일 아침` — 시간대 단어가 날짜 바로 뒤 → UNPARSED."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, "9월 2일 아침 입금")
    assert len(_unparseds(out)) >= 1


# ── customer null ─────────────────────────────────────────────────


def test_customer_null_with_onboard_mismatch() -> None:
    """customer=None 인데 `개설일 2021-03-14` → MISMATCH(onboarded_at 없음)."""
    out = date(facts_customer_null(), SectionV1.WHO, "계좌 개설일 2021-03-14")
    assert len(_mismatches(out)) == 1
    assert _mismatches(out)[0].reason is CheckReason.MISMATCH


# ── 개설일이 다름 ─────────────────────────────────────────────────


def test_wrong_onboarded_mismatch() -> None:
    """개설일이 onboarded_at(2021-03-14) 과 다름 → MISMATCH."""
    out = date(facts_fan_in(), SectionV1.WHO, "계좌 개설일 2021-04-01")
    assert len(_mismatches(out)) == 1
    assert _mismatches(out)[0].reason is CheckReason.MISMATCH


# ── 날짜는 기간 안인데 시각이 기간 밖 ────────────────────────────────


def test_date_in_period_time_out_of_period_mismatch() -> None:
    """`2022-09-02 23:30` — 날짜는 period 안이지만 시각이 period.end(22:51) 밖 → MISMATCH(쓴 정밀도)."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "2022-09-02 23:30 입금")
    assert len(_mismatches(out)) == 1
    assert _mismatches(out)[0].reason is CheckReason.MISMATCH


# ── `신규` 는 개설 단어 유지(09 10/27 결정) ─────────────────────────


def test_sinkyu_still_classified_as_onboard() -> None:
    """`신규 고객의 2022-09-02 입금` — `신규` → 개설일 분류 → onboarded_at(2021-03-14) 안 맞음 → MISMATCH.

    09 10/27 결정 유지(SCRUM-59 로 바꾸지 않음) — 08 오탐 섹션에 동작 기록.
    """
    out = date(facts_fan_in(), SectionV1.SUMMARY, "신규 고객의 2022-09-02 입금")
    bad = _mismatches(out)
    assert len(bad) == 1
    assert bad[0].reason is CheckReason.MISMATCH


# ── MISSING: WHAT_WHEN_WHERE 또는 DATE 섹션에 거래 날짜 0 ──────────


def test_what_when_where_without_transaction_date_missing() -> None:
    """v1 WHAT_WHEN_WHERE 에 거래 날짜 0개 → 그 섹션 MISSING."""
    out = verification.date_match(
        facts_fan_in(),
        [section(SectionV1.WHAT_WHEN_WHERE, "거래 상대방은 3곳이며 ACH 수단으로 입금됨")],
    )
    missings = [c for c in out if c.reason is CheckReason.MISSING]
    assert len(missings) == 1
    assert missings[0].section is SectionV1.WHAT_WHEN_WHERE
    assert missings[0].draft_value is None


def test_v2_date_section_without_transaction_date_missing() -> None:
    """v2 DATE 섹션에 거래 날짜 0개 → 그 섹션 MISSING."""
    out = verification.date_match(
        facts_fan_in(),
        [section(SectionV2.DATE, "자료 없음")],
    )
    missings = [c for c in out if c.reason is CheckReason.MISSING]
    assert len(missings) == 1
    assert missings[0].section is SectionV2.DATE


def test_other_section_without_transaction_date_no_missing() -> None:
    """다른 섹션(SUMMARY) 은 거래 날짜가 없어도 MISSING 안 남긴다(섹션 전용)."""
    out = verification.date_match(
        facts_fan_in(),
        [section(SectionV1.SUMMARY, "집중 입금 유형")],
    )
    assert all(c.reason is not CheckReason.MISSING for c in out)


def test_what_when_where_with_transaction_date_no_missing() -> None:
    """WHAT_WHEN_WHERE 에 거래 날짜 1개 있으면 MISSING 안 남긴다."""
    out = verification.date_match(
        facts_fan_in(),
        [section(SectionV1.WHAT_WHEN_WHERE, "2022-09-02 입금 3건")],
    )
    assert all(c.reason is not CheckReason.MISSING for c in out)
