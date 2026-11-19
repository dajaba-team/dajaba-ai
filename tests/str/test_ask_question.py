"""질문 속 계좌 가리기 (SCRUM-290, 정본 docs/str/04 "질문 속 계좌")."""

from __future__ import annotations

import pytest

from aml_ai.str.domain.ask_question import mask_question


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10_8000EBD30 계좌 거래 알려 줘", "10_****BD30 계좌 거래 알려 줘"),
        ("8000EBD30 은 누구 계좌야?", "****BD30 은 누구 계좌야?"),
        ("8000EBD30계좌", "****BD30계좌"),  # 한글이 바로 붙어도
        ("10_8000EBD30 과 020_C0000001", "10_****BD30 과 020_****0001"),
        ("10_8000EBD30, 8000EBD31", "10_****BD30, ****BD31"),
    ],
    ids=["full", "bare", "bare+hangul", "two-full", "full+bare"],
)
def test_account_shapes_are_masked(text: str, expected: str) -> None:
    assert mask_question(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "10_****BD30 계좌는?",  # 이미 가린 키
        "****BD30 계좌는?",  # 이미 가린 꼬리
        "2022-09-02 에 42750.50 USD 들어왔어?",  # 날짜·금액
        "20220902 거래는?",  # 숫자만 8자
        "ACH 랑 FAN_IN 이 뭐야? R02_FAN_IN 룰",  # 영문 코드값
        "WIREWIRE 는?",  # 영대문자만 8자
        "입금 상대가 몇 곳이야?",  # 계좌 없음
    ],
    ids=["masked-full", "masked-tail", "date-amount", "digits-only", "codes", "letters-only", "none"],
)
def test_non_account_text_unchanged(text: str) -> None:
    assert mask_question(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("１０＿８０００ＥＢＤ３０ 계좌는?", "10_****BD30 계좌는?"),  # 전각 계좌 키
        ("８０００ＥＢＤ３０ 계좌는?", "****BD30 계좌는?"),  # 전각 맨 계좌
        ("**8000EBD30** 알려 줘", "******BD30** 알려 줘"),  # Markdown 강조
        ("`8000EBD30` 알려 줘", "`****BD30` 알려 줘"),
        ("계좌 8000EBD30.", "계좌 ****BD30."),
        ("(10_8000EBD30)", "(10_****BD30)"),
        ("**10_8000EBD30**", "**10_****BD30**"),
        ("8000ebd30 소문자", "****bd30 소문자"),
        ("10_****BD30 그대로", "10_****BD30 그대로"),
    ],
    ids=["fw-full", "fw-bare", "md-bold", "backtick", "period", "paren", "md-bold-full", "lower", "masked"],
)
def test_review1_bypass_shapes_are_masked(text: str, expected: str) -> None:
    """추가 검토 1 — NFKC 뒤 가리기, 앞뒤 기호는 경계로만 (docs/str/04 "질문 속 계좌")."""
    assert mask_question(text) == expected
