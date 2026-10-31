"""도메인 dataclass. DB 행·LLM 응답을 도메인이 쓰기 좋은 모양으로. 규약 모양은 shared/schemas (여기 아님)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from aml_ai.shared.schemas.str import Facts, LlmNarrativeSection, NarrativeSection, Reference


@dataclass(frozen=True)
class Transaction:
    """ops.transactions 한 행. is_laundering·pattern_* 는 없다 — 정답 라벨이 서빙에 새면 안 된다 (docs/str/04).

    currency_* 는 ISO 코드(USD) — 원천 이름(US Dollar)은 transaction_reader 가 읽을 때 바꾼다.
    """

    transaction_id: int
    ts: datetime
    from_account_key: str
    to_account_key: str
    amount_paid: Decimal
    currency_paid: str
    amount_received: Decimal
    currency_received: str
    payment_format: str
    is_self_transfer: bool


@dataclass(frozen=True)
class Customer:
    """ops.customer_attributes 한 행 (합성 속성 — 규약 1.4). 없는 값은 None."""

    industry: str | None
    risk_level: str | None
    account_purpose: str | None
    onboarded_at: date | None
    country_code: str | None


@dataclass(frozen=True)
class Subject:
    """보고 대상 계좌 S(= alert.account_key)와 그 법인. 없는 값은 None (docs/str/04 "입력").

    account_entities: 경보 거래에 나오는 계좌 → entity_id. internal(같은 법인 계좌끼리) 판정용.
    accounts 에 없는 계좌는 키가 없다. entity_type 은 ops.entities.entity_type 원값(SCRUM-47).
    """

    account_key: str
    entity_id: str | None
    entity_name: str | None
    bank_name: str | None
    entity_type: str | None = None
    customer: Customer | None = None
    account_entities: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Example:
    """few-shot 예시 하나 (fewshot/*.json ↔ ai.fewshot_examples)."""

    example_id: int
    typology: str
    facts: Facts
    narrative: list[NarrativeSection]


@dataclass(frozen=True)
class GenerationResult:
    """narrative_generator 가 돌려주는 것. evidence_ids 는 아직 없다 — attach_evidence 가 붙인다."""

    narrative: list[LlmNarrativeSection]
    llm_model: str
    prompt_version: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    request_payload: dict[str, object] = field(default_factory=dict)  # generations.request (프롬프트 변수)
    raw_response: str = ""  # generations.response


@dataclass(frozen=True)
class StoredDraft:
    """verify 가 generations 에서 꺼내는 것. 수정본도 생성 당시 facts 로 대조한다."""

    generation_id: str
    draft_id: str
    facts: Facts
    evidence_transaction_ids: list[int]
    references: list[Reference]
