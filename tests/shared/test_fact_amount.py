"""`FactAmount` 패턴 — SCRUM-140 (docs/shared/01, str/04 "금액 문자열 규칙").

소수부 최소 2자리(법정 통화 표기 보장) · 최대 6자리(DB numeric(20,6) 일치).
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from aml_ai.shared.schemas.common import FactAmount

ADAPTER = TypeAdapter(FactAmount)


@pytest.mark.parametrize(
    "value",
    [
        "0.00",
        "42750.50",
        "320000000.00",
        "0.0042",  # BTC — develop ^\d+\.\d{2}$ 거부, 브랜치 통과
        "0.004200",
        "0.000001",  # BTC 1 sat — develop 거부, 브랜치 통과
        "1.23456",  # 5자리
    ],
)
def test_accept(value: str) -> None:
    ADAPTER.validate_python(value)


@pytest.mark.parametrize(
    "value",
    [
        "0.0000004",  # 7자리 — scale 넘음
        "4.2E-3",  # 지수 표기
        "-1.00",  # 음수
        "0.0",  # 1자리 (법정 통화 표기 보장 어김)
        "5",  # 소수부 없음
        "",
    ],
)
def test_reject(value: str) -> None:
    with pytest.raises(ValidationError):
        ADAPTER.validate_python(value)
