"""공통 타입. 규약 1절·안건 19 권장안."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

TransactionId = Annotated[int, Field(ge=1, description="백엔드 ops.transactions.transaction_id (bigint)")]
AccountKey = Annotated[
    str, StringConstraints(min_length=3, max_length=64), Field(description="{bank_id}_{account_id}")
]
CurrencyCode = Annotated[str, StringConstraints(min_length=3, max_length=3), Field(description="ISO 4217")]
Money = Annotated[
    Decimal, Field(decimal_places=2, description="소수 2자리 숫자 (facts.total_amount 만 문자열)")
]
Timestamp = Annotated[datetime, Field(description="ISO 8601, 초 단위, 시간대 없음 (IBM 원본)")]


class Typology(StrEnum):
    """우리 유형 enum. 규약 2절 룰 ID 와 1:1 은 아니다 — 룰 → 유형 매핑은 규약 v0.2 에서."""

    FAN_IN = "FAN_IN"
    FAN_OUT = "FAN_OUT"
    PASS_THROUGH = "PASS_THROUGH"
    CYCLE = "CYCLE"
    STACK = "STACK"
    BIPARTITE = "BIPARTITE"
    STRUCTURING = "STRUCTURING"
    NEW_ACCOUNT_LARGE = "NEW_ACCOUNT_LARGE"
    HIGH_VALUE = "HIGH_VALUE"
    DORMANT_BURST = "DORMANT_BURST"


class TypologySource(StrEnum):
    RULE = "RULE"  # 안건 8 권장: PATTERN_LABEL 삭제


class StrictModel(BaseModel):
    """규약 모델의 부모 — 모르는 필드는 거절(백엔드와 어긋남을 바로 드러낸다), snake_case."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
