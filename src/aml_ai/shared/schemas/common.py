"""공통 타입. 규약 0절·1절 (v0.2, 10/27) — docs/shared/01 "공통 타입 규칙"."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

TransactionId = Annotated[
    int, Field(ge=1, description="백엔드 ops.transactions.transaction_id (bigint, JSON 숫자)")
]
AlertId = Annotated[
    str,
    StringConstraints(pattern=r"^ALT-\d{8}-\d{6}$"),
    Field(description="ALT-{YYYYMMDD}-{6자리} (규약 2절)"),
]
AccountKey = Annotated[
    str, StringConstraints(min_length=3, max_length=64), Field(description="{bank_id}_{account_no}")
]
CurrencyCode = Annotated[
    str, StringConstraints(pattern=r"^[A-Z]{3}$"), Field(description="ISO 4217 코드. 예외 BTC (규약 0절)")
]
Money = Annotated[Decimal, Field(decimal_places=2, description="소수 2자리 숫자. facts 금액만 문자열")]
FactAmount = Annotated[
    str, StringConstraints(pattern=r"^\d+\.\d{2}$"), Field(description="facts 금액 — 소수 2자리 고정 문자열")
]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Timestamp = Annotated[datetime, Field(description="데이터 시각: ISO 8601, 초 단위, 시간대 없음 (IBM 원본)")]


def _utc_seconds(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(microsecond=0)


SystemTimestamp = Annotated[
    AwareDatetime,
    AfterValidator(_utc_seconds),
    Field(description="시스템 시각: 시간대 필수, UTC + Z, 초 단위"),
]


class Typology(StrEnum):
    """경보 typology_hint 와 facts.typology 의 값.

    규약 2절: typology_hint = 1.1 pattern_type 과 같은 열거값(앞 8개).
    뒤 5개는 패턴 라벨이 없는 룰(R03·R07·R08·교체 후보)이 쓸 수 있는 값 — 룰 → 유형 매핑은 안건 20.
    """

    FAN_IN = "FAN_IN"
    FAN_OUT = "FAN_OUT"
    GATHER_SCATTER = "GATHER_SCATTER"
    SCATTER_GATHER = "SCATTER_GATHER"
    CYCLE = "CYCLE"
    STACK = "STACK"
    BIPARTITE = "BIPARTITE"
    RANDOM = "RANDOM"
    PASS_THROUGH = "PASS_THROUGH"
    STRUCTURING = "STRUCTURING"
    NEW_ACCOUNT_LARGE = "NEW_ACCOUNT_LARGE"
    HIGH_VALUE = "HIGH_VALUE"
    DORMANT_BURST = "DORMANT_BURST"


class TypologySource(StrEnum):
    RULE = "RULE"  # 안건 8: PATTERN_LABEL 삭제


class StrictModel(BaseModel):
    """규약 모델의 부모 — 모르는 필드는 거절(백엔드와 어긋남을 바로 드러낸다), snake_case."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, str_strip_whitespace=True)
