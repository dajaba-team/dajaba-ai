"""규약 5절 — facts (대상 계좌 관점 통화별 집계). 정본 docs/str/04. enum 은 facts_enums.py."""

from __future__ import annotations

from datetime import date

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
from aml_ai.shared.schemas.str.facts_enums import Direction, EntityType, PathKind, PathStatus

MODEL_SIGNALS_MAX = 3


class SubjectFacts(StrictModel):
    entity_id: str | None
    entity_name: str | None
    entity_type: EntityType | None = None
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
    """inbound(받은 쪽 금액) / outbound(보낸 쪽 금액). 통화별, 환산 없음.

    `count`·`transaction_ids` 는 **모든** 흐름 거래(미등록 통화 포함),
    `by_currency` 는 **매핑된 통화만**(미등록 통화는 `Facts.unmapped_currencies`, SCRUM-47).
    """

    count: int = Field(ge=0)
    by_currency: list[CurrencyTotal]
    transaction_ids: list[TransactionId]

    @model_validator(mode="after")
    def _consistent(self) -> FlowFacts:
        if self.count != len(self.transaction_ids):
            raise ValueError("count must equal len(transaction_ids)")
        if sum(c.count for c in self.by_currency) > self.count:
            raise ValueError("sum of by_currency.count must not exceed count")
        return self


class IdGroupFacts(StrictModel):
    """금액 집계 없이 건수·ID 만 — internal, indirect, counterparties."""

    count: int = Field(ge=0)
    transaction_ids: list[TransactionId]


class UnmappedCurrencyAgg(StrictModel):
    """표에 없는 통화(ISO 매핑 없음) 원문 보존 — `by_currency`·대조에는 안 섞음(SCRUM-47, docs/str/04).

    서술에는 "{원문} … 대응 미확인"(05). fact 키 `unmapped_currencies.{name}` 로 근거 거래만 인용.
    """

    name: str = Field(min_length=1, description="원문 이름 그대로 — ISO 코드가 아님")
    count: int = Field(ge=1)
    transaction_ids: list[TransactionId]

    @model_validator(mode="after")
    def _count_matches_ids(self) -> UnmappedCurrencyAgg:
        if self.count != len(self.transaction_ids):
            raise ValueError("unmapped_currencies.count must equal len(transaction_ids)")
        return self


class CounterpartyBanks(StrictModel):
    """`counterparties` 집합 기준 상대 계좌의 자행·타행 분포 (SCRUM-47, docs/str/04).

    `{bank_id}` 비교 — `account_key` 의 앞부분이 대상 계좌와 같으면 same, 다르면 other.
    두 합 = `counterparties.count`.
    """

    same_bank_accounts: int = Field(ge=0)
    other_bank_accounts: int = Field(ge=0)


class PaymentFormatCount(StrictModel):
    """결제 방식별 건수 (SCRUM-47). 원본 문자열 그대로, 건수 내림차순 → 이름순 정렬 보존."""

    format: str = Field(min_length=1)
    count: int = Field(ge=1)


class AmountRange(StrictModel):
    """통화별 min/max 금액(SCRUM-47) — 매핑된 통화만, 환산·합산 없음.

    min·max 는 Decimal 소수 2자리 문자열(`CurrencyTotal.total` 과 같은 규칙).
    """

    currency: CurrencyCode
    min: FactAmount
    max: FactAmount


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
    counterparty_banks: CounterpartyBanks = Field(
        default_factory=lambda: CounterpartyBanks(same_bank_accounts=0, other_bank_accounts=0)
    )
    payment_formats: list[str]
    payment_format_counts: list[PaymentFormatCount] = Field(default_factory=list)
    amount_range: list[AmountRange] = Field(default_factory=list)
    typology: Typology | None
    typology_source: TypologySource
    customer: CustomerFacts | None
    prior_alert_count: int = Field(ge=0)
    observations: list[ObservationFacts]
    model_signals: list[str] = Field(max_length=MODEL_SIGNALS_MAX)
    unmapped_currencies: list[UnmappedCurrencyAgg] = Field(default_factory=list)
