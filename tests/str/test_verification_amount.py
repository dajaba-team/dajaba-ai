"""AMOUNT_MATCH 단위 (SCRUM-58). 정본 docs/str/06.

fixtures/facts_fan_in.json — USD total 42,750.50 · amount_range 12,500.00~16,250.50.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aml_ai.shared.schemas.str import CheckReason, CodeCheckName, SectionV1, SectionV2
from tests.str.verification_support import (
    amount,
    facts_fan_in,
    facts_total,
    facts_with_range,
)

# ---------- 정상 (match) ----------


@pytest.mark.parametrize("section", [SectionV1.SUMMARY, SectionV2.METHOD])
@pytest.mark.parametrize(
    "text",
    [
        "입금 합계 42,750.50 US Dollar",  # 뒤쪽 영문 원문
        "합계 USD 42,750.50 입금",  # 앞쪽 코드
        "합계 $42,750.50 입금",  # 앞쪽 기호
        "합계 US Dollar 42,750.50 입금",  # 앞쪽 영문 원문 (★B)
        "건당 12,500.00 US Dollar 수준",  # amount_range min (오류 주입 #29)
        "42,750.50 US Dollar의 입금",  # 조사 '의'
        "42,750.50 달러로 입금",  # 한글 표기 뒤쪽, 조사
    ],
)
def test_match_total_and_range(section: SectionV1 | SectionV2, text: str) -> None:
    checks = amount(facts_fan_in(), section, text)
    assert checks, f"no result for {text!r}"
    assert all(c.match for c in checks), [c for c in checks if not c.match]


def test_korean_compound_unit() -> None:  # 오류 주입 #2 거짓 양성
    checks = amount(facts_total("320000000.00"), SectionV1.SUMMARY, "입금 3억 2천만 US Dollar")
    assert checks and all(c.match for c in checks)


# ---------- 오탐 막기 (결과 없음) ----------


@pytest.mark.parametrize(
    "text",
    [
        # 금액이 바로 안 붙음
        "원인이 명확하지 않음",
        "회원 가입일이 2021년",
        "프랑스 발신 입금",
        # 통화 뒤에 영문·숫자가 이어짐
        "USDT 100 송금",
        "EURO 200 거래",
        # 금액 없는 통화 언급 (★B)
        "입금 통화는 US Dollar이며",
        "통화는 US Dollar 하나임",
        "US Dollar 이체가 이어짐",
        "US Dollar 거래가 많음",
    ],
)
def test_no_result_for_non_amount(text: str) -> None:
    assert amount(facts_fan_in(), SectionV1.SUMMARY, text) == []


def test_number_followed_by_count_or_date() -> None:  # 금액 모양 제외 (★B)
    checks = amount(facts_fan_in(), SectionV1.SUMMARY, "합계 42,750.50 US Dollar 3건 입금")
    assert len(checks) == 1 and checks[0].match
    assert amount(facts_fan_in(), SectionV1.SUMMARY, "US Dollar 2022-09-02 입금") == []


def test_prefers_leading_number_over_trailing() -> None:
    """통화 하나는 금액 하나와만 짝 — 앞쪽(숫자 뒤) 우선 (★B 보강)."""
    checks = amount(facts_fan_in(), SectionV1.SUMMARY, "42,750.50 US Dollar 100 송금")
    assert len(checks) == 1 and checks[0].match


# ---------- 잡기 (MISMATCH / UNPARSED) ----------


def test_mismatch_value() -> None:  # 오류 주입 #1
    checks = amount(facts_fan_in(), SectionV1.SUMMARY, "입금 32,000,000 US Dollar")
    assert checks and not any(c.match for c in checks)
    assert all(c.reason is CheckReason.MISMATCH for c in checks if not c.match)


def test_mismatch_leading_english() -> None:  # ★B 보강
    checks = amount(facts_fan_in(), SectionV1.SUMMARY, "입금 US Dollar 32,000,000")
    assert checks and not any(c.match for c in checks)
    assert all(c.reason is CheckReason.MISMATCH for c in checks if not c.match)


def test_mismatch_currency() -> None:  # 오류 주입 #15
    checks = amount(facts_total("320000000.00"), SectionV1.SUMMARY, "입금 320,000,000 EUR")
    assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks)


def test_mismatch_unmapped_currency() -> None:
    """`원`·`₩` 는 facts 에 없어 늘 MISMATCH (환산 금지 규칙)."""
    checks = amount(facts_fan_in(), SectionV1.SUMMARY, "입금 1,000 원")
    assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks)


@pytest.mark.parametrize(
    "text",
    [
        "입금 약 3억 US Dollar",  # 근사 — 오류 주입 #17
        "입금 삼억 이천만 US Dollar",  # 한글 수사 — 오류 주입 #17
        "입금 3천 US Dollar",  # 지원 안 하는 단위
        "입금 1조 US Dollar",  # 지원 안 하는 단위
        "입금 3억 이상 US Dollar",  # 근사·범위
    ],
)
def test_unparsed(text: str) -> None:
    checks = amount(facts_fan_in(), SectionV1.SUMMARY, text)
    assert checks and all(not c.match and c.reason is CheckReason.UNPARSED for c in checks)


# ---------- 보조 확인 ----------


def test_check_name() -> None:
    checks = amount(facts_fan_in(), SectionV1.SUMMARY, "입금 42,750.50 US Dollar")
    assert all(c.check is CodeCheckName.AMOUNT_MATCH for c in checks)


def test_decimal_equality() -> None:
    """42,750.50 과 42750.50 과 42750.5 는 같은 Decimal."""
    assert Decimal("42750.50") == Decimal("42750.5")
    for text in ("42,750.50 US Dollar", "42750.50 US Dollar", "42750.5 US Dollar"):
        assert all(c.match for c in amount(facts_fan_in(), SectionV1.SUMMARY, text)), text


def test_match_amount_range_min() -> None:
    """amount_range min 과 정확히 같은 값도 match (★A 3)."""
    facts = facts_with_range("1500000.00", "22000000.00")
    checks = amount(facts, SectionV1.SUMMARY, "건당 1,500,000 US Dollar")
    assert checks and all(c.match for c in checks)


# ---------- Codex adversarial 회귀 ----------


@pytest.mark.parametrize(
    "text",
    [
        "-42,750.50 US Dollar",  # 앞에 `-` 부호 — 토큰 깨짐
        "1,42,750.50 US Dollar",  # 앞에 `,` + 숫자 조각
        "US Dollar 42,750.50,000",  # 뒤에 `,` + 숫자 조각
    ],
)
def test_broken_token_unparsed(text: str) -> None:
    """Codex adversarial [high] #1 — 토큰 경계 깨지면 UNPARSED (조용히 통과 아님)."""
    checks = amount(facts_fan_in(), SectionV1.SUMMARY, text)
    assert checks and all(not c.match and c.reason is CheckReason.UNPARSED for c in checks)


@pytest.mark.parametrize("text", ["USD 삼억", "USD 약 3억"])
def test_leading_english_numeral_or_approx_unparsed(text: str) -> None:
    """Codex adversarial [high] #2 — 통화 뒤 수사·근사도 UNPARSED (통화 위치로 우회 못 함)."""
    checks = amount(facts_fan_in(), SectionV1.SUMMARY, text)
    assert checks and all(not c.match and c.reason is CheckReason.UNPARSED for c in checks)


def test_cheonman_longest_match_both_sides() -> None:
    """Codex adversarial [medium] #3 — `3천만` 은 지원 단위, 통화 위치 바뀌어도 같게 처리."""
    facts = facts_fan_in()
    for text in ("USD 3천만", "3천만 US Dollar"):
        checks = amount(facts, SectionV1.SUMMARY, text)
        # 30,000,000 ≠ facts total 42,750.50 → MISMATCH (UNPARSED 아님)
        assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks), text


def test_won_symbol_leading_mismatch() -> None:
    """Codex adversarial [medium] #4 — `₩1,000` 앞쪽 기호도 쌍짓기, facts 에 KRW 없어 MISMATCH."""
    checks = amount(facts_fan_in(), SectionV1.SUMMARY, "₩1,000 입금")
    assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks)
