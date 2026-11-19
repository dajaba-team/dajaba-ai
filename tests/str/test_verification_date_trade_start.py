"""DATE_MATCH `거래 시작` 신호 나누기 (SCRUM-290 2/2 추가 검토 1·2, docs/str/06 DATE_MATCH 줄 ②, 09 2026-11-20).

개설 신호 = 바로 뒤 `일`(일시 아님) · 같은 절 앞 10자 `고객`. 기간 신호 = `일시` · 시각 있음 · `기간`/`부터`/`까지`.
개설 둘 다 + 기간 없음 → 개설일 · 개설 신호 없음 → 거래 날짜 · 그 밖 → UNPARSED. `거래 개시` 는 개설 단어 아님.
fan_in: period 2022-09-02 00:14~22:51 · customer.onboarded_at 2021-03-14.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CheckReason, SectionV2
from tests.str.verification_support import date, facts_fan_in


def _src(check) -> str:
    return check.source_value or ""


@pytest.mark.parametrize(
    "text",
    [
        "거래 시작일시는 2022-09-02T00:14:00, 거래 종료일시는 2022-09-02T22:51:00으로 보여요.",
        "거래 시작은 2022-09-02 00:14, 끝은 2022-09-02 22:51이에요.",
    ],
    ids=["F3-iso", "start-eun"],
)
def test_period_start_wording_is_transaction(text: str) -> None:
    out = date(facts_fan_in(), SectionV2.DATE, text)
    assert len(out) == 2 and all(c.match for c in out)
    assert all("period" in _src(c) for c in out)


def test_customer_start_day_wrong_date_is_onboard_mismatch() -> None:
    (out,) = date(facts_fan_in(), SectionV2.SUBJECT, "고객과의 거래 시작일은 2022-09-02이에요.")
    assert out.match is False and "onboarded_at" in _src(out)


@pytest.mark.parametrize(
    "text",
    ["고객과의 거래 시작일은 2021-03-14이에요.", "개설일은 2021-03-14 이에요."],
    ids=["customer-start-day", "gaeseol"],
)
def test_onboard_wordings_match_onboarded_at(text: str) -> None:
    (out,) = date(facts_fan_in(), SectionV2.SUBJECT, text)
    assert out.match is True and "onboarded_at" in _src(out)


def test_review2_gaesi_is_not_onboard_word() -> None:
    """추가 검토 2 반례 — `거래 개시` 는 개설 단어가 아님 → 2021-03-14 는 거래 날짜, 기간 밖 MISMATCH."""
    out = date(
        facts_fan_in(),
        SectionV2.DATE,
        "입금 거래 개시일시는 2021-03-14, 거래 종료일시는 2022-09-02T22:51:00이에요.",
    )
    first = out[0]
    assert first.draft_value == "2021-03-14" and first.match is False


@pytest.mark.parametrize(
    "text",
    [
        "당행 고객과의 첫 거래 시작일시는 2022-09-02T00:14:00이에요.",  # 추가 검토 2 반례 — 고객 + 일시
        "거래 시작일은 2021-03-14이에요.",  # 개설 신호 하나만(고객 없음)
        "고객 거래 시작은 2021-03-14이에요.",  # 개설 신호 하나만(시작일 아님)
        "고객과의 거래 시작일은 2022-09-02 00:14이에요.",  # 개설 둘 + 시각
        "고객과의 거래 시작일은 2022-09-02부터예요.",  # 개설 둘 + 부터
    ],
    ids=["customer-ilsi", "day-only", "customer-only", "with-time", "with-buteo"],
)
def test_conflicting_or_partial_signals_are_unparsed(text: str) -> None:
    (out,) = date(facts_fan_in(), SectionV2.SUBJECT, text)
    assert out.match is False and out.reason is CheckReason.UNPARSED


def test_customer_far_from_trade_start_is_transaction() -> None:
    (out,) = date(
        facts_fan_in(), SectionV2.SUBJECT, "고객 계좌로 들어온 입금들의 거래 시작은 2022-09-02 00:14이에요."
    )
    assert out.match is True and "period" in _src(out)


# ───────── 추가 검토 3 — 같은 절 거래 방향 낱말이면 개설 신호가 있어도 거래 날짜 ─────────


def test_review3_direction_word_wrong_date_is_mismatch() -> None:
    (out,) = date(facts_fan_in(), SectionV2.SUBJECT, "고객의 입금 거래 시작일은 2021-03-14이에요.")
    assert out.match is False and "period" in _src(out)


def test_review3_direction_word_period_date_matches() -> None:
    (out,) = date(facts_fan_in(), SectionV2.SUBJECT, "고객의 입금 거래 시작일은 2022-09-02이에요.")
    assert out.match is True and "period" in _src(out)


# ───────── 추가 검토 4 — 방향 낱말은 `거래 시작` 바로 앞에서 꾸밀 때만 ─────────


@pytest.mark.parametrize(
    "text",
    [
        "고객과의 거래 시작일은 2022-09-02이며 입금은 3건이에요.",
        "받은 자료에 따르면 고객과의 거래 시작일은 2022-09-02이에요.",
    ],
    ids=["direction-elsewhere", "badeun-jaryo"],
)
def test_review4_direction_word_elsewhere_keeps_onboard(text: str) -> None:
    out = [c for c in date(facts_fan_in(), SectionV2.SUBJECT, text) if c.draft_value == "2022-09-02"]
    assert len(out) == 1 and out[0].match is False and "onboarded_at" in _src(out[0])


def test_review4_direction_word_without_space_modifies() -> None:
    (out,) = date(facts_fan_in(), SectionV2.SUBJECT, "고객의 입금거래 시작일은 2022-09-02이에요.")
    assert out.match is True and "period" in _src(out)


# ───────── 추가 검토 5 — 방향 낱말과 `거래 시작` 사이 수평 공백·탭 묶음 ─────────


@pytest.mark.parametrize("gap", ["  ", "\t", " \t "], ids=["two-spaces", "tab", "mixed"])
def test_review5_horizontal_whitespace_gap_still_modifies(gap: str) -> None:
    wrong = date(facts_fan_in(), SectionV2.SUBJECT, f"고객의 입금{gap}거래 시작일은 2021-03-14이에요.")
    assert len(wrong) == 1 and wrong[0].match is False and "period" in _src(wrong[0])
    right = date(facts_fan_in(), SectionV2.SUBJECT, f"고객의 입금{gap}거래 시작일은 2022-09-02이에요.")
    assert len(right) == 1 and right[0].match is True and "period" in _src(right[0])


# ───────── 추가 검토 6 — 유니코드 수평 공백 묶음 · 유니코드 줄 경계 ─────────

UNICODE_GAPS = ["\u3000", "\u00a0", "\u2002", "\u2003", "\u2009", " \u3000\t\u00a0"]
GAP_IDS = ["ideographic", "nbsp", "en", "em", "thin", "mixed"]


@pytest.mark.parametrize("gap", UNICODE_GAPS, ids=GAP_IDS)
def test_review6_unicode_horizontal_space_still_modifies(gap: str) -> None:
    wrong = date(facts_fan_in(), SectionV2.SUBJECT, f"고객의 입금{gap}거래 시작일은 2021-03-14이에요.")
    assert len(wrong) == 1 and wrong[0].match is False and "period" in _src(wrong[0])
    right = date(facts_fan_in(), SectionV2.SUBJECT, f"고객의 입금{gap}거래 시작일은 2022-09-02이에요.")
    assert len(right) == 1 and right[0].match is True and "period" in _src(right[0])


@pytest.mark.parametrize("brk", ["\n", "\r", "\u2028", "\u2029"], ids=["lf", "cr", "ls", "ps"])
def test_review6_line_breaks_are_clause_boundaries(brk: str) -> None:
    """앞 줄의 `고객`(10자 안)은 개설 신호가 아님 — 네 줄 경계가 같게 동작 → 시작일만 남아 UNPARSED."""
    out = date(facts_fan_in(), SectionV2.SUBJECT, f"고객이에요{brk}거래 시작일은 2021-03-14이에요.")
    assert len(out) == 1 and out[0].match is False and out[0].reason is CheckReason.UNPARSED


@pytest.mark.parametrize("brk", ["\n", "\r", "\u2028", "\u2029"], ids=["lf", "cr", "ls", "ps"])
def test_review6_direction_and_customer_across_line_break(brk: str) -> None:
    """줄 경계 너머의 `고객`·`입금` 은 둘 다 안 봄 — 개설일로 대조되지 않고 UNPARSED."""
    (out,) = date(facts_fan_in(), SectionV2.SUBJECT, f"고객과의 입금{brk}거래 시작일은 2022-09-02이에요.")
    assert out.match is False and out.reason is CheckReason.UNPARSED
