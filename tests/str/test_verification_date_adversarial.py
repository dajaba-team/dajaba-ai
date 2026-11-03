"""SCRUM-59 Codex adversarial 2·3차 반영 회귀.

- 2차: 한국어 날짜 뒤 초 흡수(regex 자체 시각 그룹 제거·공용 소비기 통일), 확장된 span 자기 자신 경쟁 금지.
- 3차: malformed 시각 토큰(끊긴 숫자) UNPARSED, tab·newline 공백 소비.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CheckReason, SectionV1
from tests.str.verification_support import date, facts_fan_in

# ── 한국어 날짜 뒤 초 흡수(2차 high) ─────────────────────────────────


@pytest.mark.parametrize(
    "text,expected_mismatch",
    [
        ("2022년 9월 2일 22:51:30 입금", True),  # period.end 는 22:51:00, 30초라 밖
        ("2022년 9월 2일 22:51:00 입금", False),  # 초 00 환원 → 정확히 period.end
        ("2022년 9월 2일 00:14:00 입금", False),  # 초 00 환원 → period.start
    ],
)
def test_korean_date_seconds_consumed(text: str, expected_mismatch: bool) -> None:
    """한국어 날짜 뒤 `:30` 초가 조용히 버려지지 않음 — 공용 소비기가 초까지 읽음."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, text)
    bads = [c for c in out if not c.match and c.reason is CheckReason.MISMATCH]
    assert bool(bads) is expected_mismatch, [(c.draft_value, c.source_value, c.reason) for c in out]


@pytest.mark.parametrize("text", ["2022년 9월 2일 14:30:99 입금", "2022년 9월 2일 14:30:60 입금"])
def test_korean_date_invalid_seconds_unparsed(text: str) -> None:
    """한국어 날짜 뒤 초 범위 밖 → UNPARSED (조용히 통과 금지)."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, text)
    assert any(c.reason is CheckReason.UNPARSED for c in out), [(c.draft_value, c.reason) for c in out]


# ── 확장된 날짜 span 이 자기 자신과 경쟁하지 않음(2차 medium) ──


@pytest.mark.parametrize(
    "text",
    [
        "개설일 2021/03/14 14:30",  # SLASH + 시각
        "개설일 2021.3.14 14:30",  # DOT + 시각
        "개설일 2021-03-14 14:30",  # ISO + 시각 (기준 — 지금도 match)
        "개설일 2021년 3월 14일 14:30",  # KO + 시각
    ],
)
def test_onboard_classification_cross_formats(text: str) -> None:
    """`개설일` 바로 뒤 날짜(모든 형식) + 시각 — 확장된 span 이 자기 자신과 경쟁해 UNPARSED 안 됨."""
    out = date(facts_fan_in(), SectionV1.WHO, text)
    matches = [c for c in out if c.match and (c.source_value or "").startswith("onboarded_at")]
    assert matches, [(c.draft_value, c.source_value, c.reason) for c in out]


# ── malformed 시각 토큰(끊긴 숫자) → UNPARSED (3차 high) ──


@pytest.mark.parametrize(
    "text",
    [
        "2022-09-02 23:300 입금",  # ISO + 분 자릿수 넘침
        "2022-09-02 22:51:300 입금",  # ISO + 초 자릿수 넘침
        "9월 2일 23:300 입금",
        "2022/09/02 22:51:300 입금",
        "2022년 9월 2일 23:300 입금",
    ],
)
def test_malformed_time_token_is_unparsed(text: str) -> None:
    """시각 모양 토큰이 깨져 있으면(뒤 숫자 더 붙음) 날짜만 보고 넘어가지 않고 UNPARSED."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, text)
    assert any(c.reason is CheckReason.UNPARSED for c in out), [(c.draft_value, c.reason) for c in out]


# ── 탭·개행 공백 소비기 통일(3차 medium) ──


@pytest.mark.parametrize(
    "text",
    [
        "2022/09/02\n23:30 입금",  # SLASH + newline
        "2022년 9월 2일\t23:30 입금",  # KO + tab
        "9월 2일\n23:30 입금",  # KO_NOYEAR + newline
        "2022-09-02\t23:30 입금",  # ISO + tab
    ],
)
def test_whitespace_variants_consumed(text: str) -> None:
    """space 뿐 아니라 tab·newline 로 분리된 시각도 소비기가 받음 → 기간 밖은 MISMATCH."""
    out = date(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, text)
    assert any(not c.match and c.reason is CheckReason.MISMATCH for c in out), [
        (c.draft_value, c.source_value, c.reason) for c in out
    ]
