"""규약 5절 — facts (대상 계좌 관점 통화별 집계). 정본 docs/str/04."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, model_validator

from aml_ai.shared.schemas.common import (
    AccountKey,
    CurrencyCode,
    FactAmount,
    StrictModel,
    Timestamp,
    TransactionId,
    Typology,
    TypologySource,
)

MODEL_SIGNALS_MAX = 3


class Direction(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    MIXED = "MIXED"
    INTERNAL = "INTERNAL"  # inbound·outbound 둘 다 0 (법인 내 이동만)


class SubjectFacts(StrictModel):
    entity_id: str | None
    entity_name: str | None
    account_key: AccountKey


class PeriodFacts(StrictModel):
    start: Timestamp
    end: Timestamp

    @model_validator(mode="after")
    def _ordered(self) -> PeriodFacts:
        if self.start > self.end:
            raise ValueError("period.start must be <= period.end")
        return self


class CurrencyTotal(StrictModel):
    currency: CurrencyCode
    total: FactAmount = Field(description="Decimal 합 문자열, 환산 없음")
    count: int = Field(ge=1)
    transaction_ids: list[TransactionId]

    @model_validator(mode="after")
    def _count_matches_ids(self) -> CurrencyTotal:
        if self.count != len(self.transaction_ids):
            raise ValueError("by_currency.count must equal len(transaction_ids)")
        return self


class FlowFacts(StrictModel):
    """inbound(받은 쪽 금액) / outbound(보낸 쪽 금액). 통화별, 환산 없음."""

    count: int = Field(ge=0)
    by_currency: list[CurrencyTotal]
    transaction_ids: list[TransactionId]

    @model_validator(mode="after")
    def _consistent(self) -> FlowFacts:
        if self.count != len(self.transaction_ids):
            raise ValueError("count must equal len(transaction_ids)")
        if sum(c.count for c in self.by_currency) != self.count:
            raise ValueError("sum of by_currency.count must equal count")
        return self


class IdGroupFacts(StrictModel):
    """금액 집계 없이 건수·ID 만 — internal, indirect, counterparties."""

    count: int = Field(ge=0)
    transaction_ids: list[TransactionId]


class PathKind(StrEnum):
    CYCLE = "CYCLE"
    STACK = "STACK"


class PathStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class PathFacts(StrictModel):
    """경로형 경보(R04·R05) 확인 결과. VERIFIED 일 때만 인용·LLM 전달 (docs/str/04 "경로")."""

    kind: PathKind | None
    status: PathStatus
    count: int = Field(ge=0)
    max_hops: int = Field(ge=0)
    max_accounts: int = Field(ge=0)
    transaction_ids: list[TransactionId]


class CustomerFacts(StrictModel):
    industry: str | None
    risk_level: str | None
    account_purpose: str | None
    onboarded_at: date | None
    country_code: str | None


class ObservationFacts(StrictModel):
    """reasons[] 의 관측값만. 기여값은 없다 (안건 3)."""

    name: str
    value: float
    unit: str | None
    window_start: Timestamp | None
    window_end: Timestamp | None
    basis: str | None
    baseline: float | None


class Facts(StrictModel):
    """LLM 이 보는 전부(마스킹본)이자 검증이 대조하는 정본. 계산 규칙은 docs/str/04."""

    reporting_institution: str | None
    subject: SubjectFacts
    period: PeriodFacts
    inbound: FlowFacts
    outbound: FlowFacts
    internal: IdGroupFacts
    indirect: IdGroupFacts
    paths: PathFacts | None
    excluded_self_transfer_count: int = Field(ge=0)
    direction: Direction
    counterparties: IdGroupFacts
    payment_formats: list[str]
    typology: Typology | None
    typology_source: TypologySource
    customer: CustomerFacts | None
    prior_alert_count: int = Field(ge=0)
    observations: list[ObservationFacts]
    model_signals: list[str] = Field(max_length=MODEL_SIGNALS_MAX)
