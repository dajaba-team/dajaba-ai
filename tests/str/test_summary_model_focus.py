"""model_focus 숫자 거부 — 신호 이름을 지운 뒤 남은 글자에 숫자 있을 때만 null (SCRUM-129 ★A 4).

- 신호 이름만 썼으면 통과 (이름이 `account_in_counterparties_24h` 처럼 숫자 포함이어도)
- 이름 밖에 `3건`·`24시간` 같은 관측 수치가 섞이면 null + 로그
- 본문·숫자 안 찍음
"""

from __future__ import annotations

import pytest

from aml_ai.str.application.summary_service import filter_model_focus


@pytest.fixture
def signals() -> list[str]:
    return ["account_in_counterparties_24h", "high_amount_in_period"]


def test_name_only_passes(signals: list[str]) -> None:
    """신호 이름만 — 통과 (이름 지운 나머지가 공백·구두점)."""
    out, rejected = filter_model_focus("account_in_counterparties_24h", signals)
    assert out == "account_in_counterparties_24h"
    assert rejected is False


def test_two_names_joined_passes(signals: list[str]) -> None:
    """두 이름을 그대로 이어도 통과."""
    out, rejected = filter_model_focus("account_in_counterparties_24h, high_amount_in_period", signals)
    assert out == "account_in_counterparties_24h, high_amount_in_period"
    assert rejected is False


def test_template_single_name_passes(signals: list[str]) -> None:
    """프롬프트 틀 — "모델은 {이름} 신호를 가장 크게 봄" (숫자는 이름 안에만 있음 → 통과)."""
    raw = "모델은 account_in_counterparties_24h 신호를 가장 크게 봄"
    out, rejected = filter_model_focus(raw, signals)
    assert out == raw
    assert rejected is False


def test_template_two_names_passes(signals: list[str]) -> None:
    """프롬프트 틀 — "모델은 {이름}·{이름} 신호를 크게 봄" (숫자는 이름 안에만)."""
    raw = "모델은 account_in_counterparties_24h·high_amount_in_period 신호를 크게 봄"
    out, rejected = filter_model_focus(raw, signals)
    assert out == raw
    assert rejected is False


def test_name_with_outside_digit_rejected(signals: list[str]) -> None:
    """이름 밖 "3건" 섞임 — null."""
    out, rejected = filter_model_focus("account_in_counterparties_24h — 3건 집중", signals)
    assert out is None
    assert rejected is True


def test_pure_digit_rejected(signals: list[str]) -> None:
    """이름과 무관한 숫자만 — null."""
    out, rejected = filter_model_focus("42750.50 USD 집중 입금", signals)
    assert out is None
    assert rejected is True


def test_null_input_passes(signals: list[str]) -> None:
    """LLM 이 null 을 낸 경우 그대로."""
    out, rejected = filter_model_focus(None, signals)
    assert out is None
    assert rejected is False


def test_empty_signals_digit_still_rejected() -> None:
    """signals 가 없으면 모든 숫자가 "이름 밖" — 숫자 있으면 null."""
    out, rejected = filter_model_focus("합계 42건", [])
    assert out is None
    assert rejected is True
