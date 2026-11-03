"""SCRUM-59 — 괄호 관측 분기 집중 테스트 (★B 보충 핵심).

- 괄호 바로 앞 `관측값(` → observation
- 괄호 안 `관측 구간` → observation
- 괄호 밖 관측 구간 → 거래 날짜로 분류(거짓 양성 감수)
- 괄호 안 관측 + 개설 단어 둘 다 → UNPARSED
- facts.observations 비었거나 window 와 안 맞으면 MISMATCH
- 주입 16·21(통과해야 함)
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CheckReason, SectionV1
from tests.str.verification_support import date, facts_fan_in, facts_no_observations


def _mismatches(checks: list) -> list:
    return [c for c in checks if not c.match]


def _only_matches(checks: list) -> list:
    return [c for c in checks if c.match]


def _unparseds(checks: list) -> list:
    return [c for c in checks if c.reason is CheckReason.UNPARSED]


# ── 괄호 **바로 앞** `관측값(` (v1 녹화 모양) ────────────────────────


def test_bracket_prefix_observation_word_pulls_dates_into_observation() -> None:
    text = "모델 관측값(2022-09-02T00:00:00부터 2022-09-03T00:00:00까지, 24시간 기준)은 3.0으로 제시됨"
    out = date(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, text)
    matches = _only_matches(out)
    assert len(matches) == 2
    assert all("observation" in (c.source_value or "") for c in matches)


def test_bracket_prefix_with_whitespace_before_bracket() -> None:
    """`관측값 (…)` — 괄호 바로 앞 공백은 허용(공백 제외 뒤)."""
    text = "모델 관측값 (2022-09-02T00:00:00부터 2022-09-03T00:00:00까지)"
    out = date(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, text)
    assert len(_only_matches(out)) == 2
    assert all("observation" in (c.source_value or "") for c in _only_matches(out))


def test_bracket_prefix_observation_fails_when_facts_has_no_observations() -> None:
    """괄호 모양은 맞는데 facts.observations 가 비어 있으면 MISMATCH."""
    text = "모델 관측값(2022-09-02T00:00:00부터 2022-09-03T00:00:00까지)"
    out = date(facts_no_observations(), SectionV1.WHY_SUSPICIOUS, text)
    assert all(not c.match for c in out)
    assert all(c.reason is CheckReason.MISMATCH for c in out)


# ── 괄호 **안** `관측 구간` (v2 녹화 모양) ───────────────────────────


def test_bracket_inside_observation_word() -> None:
    text = "모델 관측값(관측 구간: 2022-09-02T00:00:00~2022-09-03T00:00:00 기준)에서 3.0 관측됨"
    out = date(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, text)
    matches = _only_matches(out)
    assert len(matches) == 2
    assert all("observation" in (c.source_value or "") for c in matches)


# ── 괄호 **밖** 관측 구간 — 거래 날짜로 분류 ─────────────────────────


def test_observation_outside_bracket_classified_as_transaction() -> None:
    """`관측 구간은 2022-09-03T00:00:00까지` — 괄호 밖이라 거래 날짜로 분류 → period 밖 MISMATCH.

    거짓 양성 감수 원칙으로 지금 규칙의 결과를 그대로. 08 오탐 섹션에 동작 기록.
    """
    out = date(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, "관측 구간은 2022-09-03T00:00:00까지임")
    assert any(not c.match and c.reason is CheckReason.MISMATCH for c in out)


# ── 괄호 안 관측 + 개설 단어 → UNPARSED ──────────────────────────────


def test_bracket_with_observation_and_onboard_unparsed() -> None:
    """한 괄호 안에 관측 단어 + 개설 단어 → UNPARSED(용도 애매)."""
    text = "(관측 구간과 개설일 비교: 2021-03-14 2022-09-02)"
    out = date(facts_fan_in(), SectionV1.WHY_SUSPICIOUS, text)
    assert len(_unparseds(out)) >= 1


# ── 주입 16·21 (통과해야 함) ────────────────────────────────────────


def test_injection_16_who_section_birthdate_matches() -> None:
    """주입 16 — WHO 섹션의 개설일 `2021년 3월 14일` → match."""
    out = date(facts_fan_in(), SectionV1.WHO, "계좌 개설일은 2021년 3월 14일임")
    assert len(_only_matches(out)) == 1
    assert "onboarded_at" in (_only_matches(out)[0].source_value or "")


def test_injection_21_one_sentence_two_dates_nearest_wins() -> None:
    """주입 21 — `2021년 3월 14일 개설, 2022년 9월 2일 47건 입금`.

    `개설` 과 가까운 쪽: `2021년 3월 14일` → 개설일(match), `2022년 9월 2일` → 거래 날짜(period 안 match).
    """
    out = date(
        facts_fan_in(),
        SectionV1.WHAT_WHEN_WHERE,
        "2021년 3월 14일 개설, 2022년 9월 2일 47건 입금",
    )
    matches = _only_matches(out)
    assert len(matches) == 2
    sources = {c.source_value for c in matches}
    assert any("onboarded_at" in (s or "") for s in sources)
    assert any("period" in (s or "") for s in sources)
