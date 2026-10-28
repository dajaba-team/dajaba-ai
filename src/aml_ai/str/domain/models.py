"""도메인 dataclass. DB 행·LLM 응답을 도메인이 쓰기 좋은 모양으로. 규약 모양은 shared/schemas (여기 아님)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from aml_ai.shared.schemas.str import Facts, LlmNarrativeSection, NarrativeSection, Reference


@dataclass(frozen=True)
class Transaction:
    """ops.transactions 한 행. is_laundering·pattern_* 는 없다 — 정답 라벨이 서빙에 새면 안 된다 (docs/str/04)."""

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
class Subject:
    """대상 계좌·엔티티·고객 속성. 없는 값은 None."""

    account_keys: tuple[str, ...]
    entity_id: str | None
    entity_name: str | None
    bank_name: str | None
    industry: str | None = None
    risk_level: str | None = None
    account_purpose: str | None = None
    onboarded_at: date | None = None
    country_code: str | None = None


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
