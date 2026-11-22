"""SCRUM-310 계좌 원문 검사(순수, 추가 검토 2) — 명시적 계좌 키 · 케이스 계좌 6자 조각 · 정확 일치 후보 (str/10)."""

from __future__ import annotations

import pytest

from aml_ai.str.domain.raw_account import case_fragment_hit, exact_candidates, explicit_key, normalized

CASE = {"10_8000EBD30", "020_C0000001"}


@pytest.mark.parametrize(
    "raw", ["10_12345", "10_8000EBD30", "１０＿８０００ＥＢＤ３０", "020_C0000001", "123456_ABCDEF012"]
)
def test_explicit_key_any_length(raw: str) -> None:
    assert explicit_key([f"상대 계좌 {raw} 로"])


@pytest.mark.parametrize(
    "ok", ["대상 계좌는 10_****BD30임.", "FAN_IN 유형", "account_in_counterparties_24h 신호", "****BD30"]
)
def test_explicit_key_masked_or_not_key(ok: str) -> None:
    assert not explicit_key([ok])


def test_explicit_key_across_section_boundary() -> None:
    assert explicit_key(["상대 계좌 10_", "8000EBD30 로 보냄."])


@pytest.mark.parametrize(
    "text",
    ["8000EBD30", "앞 8000EB 로", "000EBD 끝", "80-00-EB-D3-0", "80 00 EB D3 0", "C0000001", "20_C00000"],
)
def test_case_fragments_detected(text: str) -> None:
    assert case_fragment_hit([f"상대 계좌 {text} 임"], CASE)


@pytest.mark.parametrize(
    "ok",
    [
        "대상 계좌는 10_****BD30임.",
        "****BD30 의 뒤 4자리",
        "입금 3건 · 2022-09-02 · 42,750.50 미국 달러(USD)",
        "0.3333333333333333",
    ],
)
def test_case_fragments_masked_and_normal_pass(ok: str) -> None:
    assert not case_fragment_hit([ok], CASE)


def test_case_fragment_across_boundary() -> None:
    assert not case_fragment_hit(["상대 계좌 800"], CASE) and not case_fragment_hit(["0EBD3 로"], CASE)
    assert case_fragment_hit(["상대 계좌 800", "0EBD3 로"], CASE)


def test_normalized_removes_separators_and_masked_tail() -> None:
    assert normalized(["a-b c.d_e", "****BD30 f"]) == "ABCDE|F"


def test_exact_candidates_joins_short_separators_and_boundary() -> None:
    c = exact_candidates(["계좌 80 00-EBD", "30 로"])
    assert "8000EBD30" in c and all(any(ch.isdigit() for ch in x) and 6 <= len(x) <= 24 for x in c)
    assert exact_candidates(["대상 10_****BD30 · Sole Proprietorship"]) == []


def test_bank_prefix_alone_is_not_a_fragment() -> None:
    """은행 번호(6자리까지)는 가린 표기에서도 보이는 값 — 그것만으로는 원문 아님(★ R02 실측 594건 오탐 원인)."""
    assert not case_fragment_hit(["대상 계좌는 800102_****BD30임."], {"800102_8000EBD30"})
    assert case_fragment_hit(["대상 계좌는 800102_8000EB 임."], {"800102_8000EBD30"})
