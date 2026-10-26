"""규약 5절 — STR 초안·검증·요약. facts 와 narrative 의 정본 모양 (docs/str/04, 05, 06)."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field, field_validator

from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.common import (
    AccountKey,
    StrictModel,
    Timestamp,
    TransactionId,
    Typology,
    TypologySource,
)

# ---------- facts (docs/str/04) ----------


class Direction(StrEnum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    MIXED = "MIXED"


class CustomerFacts(StrictModel):
    industry: str | None = None
    risk_level: str | None = None
    account_purpose: str | None = None
    onboarded_at: date | None = None
    country_code: str | None = None


class Facts(StrictModel):
    """LLM 이 보는 전부이자 검증이 대조하는 정본. 계산 규칙은 docs/str/04."""

    reporting_institution: str | None
    subject_entity_id: str | None
    subject_entity_name: str | None
    subject_account_keys: list[AccountKey] = Field(min_length=1)
    period_start: Timestamp
    period_end: Timestamp
    transaction_count: int = Field(ge=0)
    total_amount: str = Field(pattern=r"^\d+\.\d{2}$", description="문자열, 소수 2자리 고정. float 금지")
    currency: str
    mixed_currency: bool
    direction: Direction
    counterparty_count: int = Field(ge=0)
    payment_formats: list[str]
    typology: Typology
    typology_source: TypologySource
    customer: CustomerFacts | None
    prior_alert_count: int = Field(ge=0)
    top_reasons: list[str] = Field(default_factory=list, max_length=3)


# ---------- narrative (docs/str/05) ----------


class Section(StrEnum):
    SUMMARY = "SUMMARY"
    WHO = "WHO"
    WHAT_WHEN_WHERE = "WHAT_WHEN_WHERE"
    HOW = "HOW"
    WHY_SUSPICIOUS = "WHY_SUSPICIOUS"
    CONCLUSION = "CONCLUSION"


class NarrativeSection(StrictModel):
    section: Section
    text: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[TransactionId] = Field(default_factory=list)


class NarrativeOut(StrictModel):
    """LLM 출력 스키마. 길이 6, 섹션 enum 각 1회. 어기면 LLM_INVALID_OUTPUT (1회 재생성 뒤)."""

    narrative: list[NarrativeSection] = Field(min_length=6, max_length=6)

    @field_validator("narrative")
    @classmethod
    def _each_section_once(cls, v: list[NarrativeSection]) -> list[NarrativeSection]:
        seen = [s.section for s in v]
        if sorted(seen) != sorted(Section):
            raise ValueError("each of the 6 sections exactly once")
        return v


class Reference(StrictModel):
    """RAG 참고 사례 (docs/str/10). 응답 generation_meta.references."""

    doc_id: str
    doc_title: str
    page: int
    score: float
    text: str | None = Field(default=None, max_length=600, description="프롬프트용. 응답에는 보통 생략")


class GenerationMeta(StrictModel):
    llm_model: str
    prompt_version: str
    few_shot_ids: list[int]
    references: list[Reference] = Field(default_factory=list)
    retrieval_version: str | None = None
    server_version: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


# ---------- POST /v1/str/drafts ----------


class PriorAlert(StrictModel):
    alert_id: int
    rule_id: str
    outcome: str | None = None  # LLM 에는 주지 않는다 — 건수만 (docs/str/04)


class DraftRequest(StrictModel):
    draft_id: str
    case_no: str
    alert: Alert
    transaction_ids: list[TransactionId] = Field(
        min_length=1, description="근거 거래. 안건 7 뒤 evidence_transaction_ids 로 바뀔 수 있음"
    )
    prior_alerts: list[PriorAlert] = Field(default_factory=list)
    investigator_notes: str | None = Field(default=None, max_length=4000)
    reporting_institution: str | None = None


class DraftResponse(StrictModel):
    draft_id: str
    facts: Facts
    narrative: list[NarrativeSection]
    generation_meta: GenerationMeta
    verification: VerifyResponse | None = Field(default=None, description="안건 17: MVP 는 None (분리)")


# ---------- POST /v1/str/verify (docs/str/06) ----------


class CodeCheckName(StrEnum):
    AMOUNT_MATCH = "AMOUNT_MATCH"
    DATE_MATCH = "DATE_MATCH"
    COUNTERPARTY_COUNT = "COUNTERPARTY_COUNT"
    EVIDENCE_IN_SCOPE = "EVIDENCE_IN_SCOPE"


class LlmCheckName(StrEnum):
    FIVE_W_ONE_H_COMPLETE = "FIVE_W_ONE_H_COMPLETE"
    TYPOLOGY_CONSISTENT = "TYPOLOGY_CONSISTENT"
    NO_UNSUPPORTED_CLAIM = "NO_UNSUPPORTED_CLAIM"
    NO_SPECULATION = "NO_SPECULATION"
    NO_INSTRUCTION_TEXT = "NO_INSTRUCTION_TEXT"


class VerifyStatus(StrEnum):
    PASSED = "PASSED"
    CODE_FAILED = "CODE_FAILED"
    LLM_FAILED = "LLM_FAILED"
    VERIFY_UNAVAILABLE = "VERIFY_UNAVAILABLE"  # 평가자 호출 실패 — passed=false 가 아님 (안건 9)


class CodeCheck(StrictModel):
    check: CodeCheckName
    section: Section | None = Field(default=None, description="None = 초안 전체")
    draft_value: str | None
    source_value: str | None
    match: bool


class LlmCheck(StrictModel):
    check: LlmCheckName
    comment: str = Field(max_length=500, description="score 보다 앞 — 평가자가 근거를 먼저 쓴다")
    score: int = Field(ge=1, le=5)


class JudgeOut(StrictModel):
    """judge LLM 출력 스키마. 5개, 각 1회."""

    checks: list[LlmCheck] = Field(min_length=5, max_length=5)

    @field_validator("checks")
    @classmethod
    def _each_check_once(cls, v: list[LlmCheck]) -> list[LlmCheck]:
        if sorted(c.check for c in v) != sorted(LlmCheckName):
            raise ValueError("each of the 5 checks exactly once")
        return v


class VerifyRequest(StrictModel):
    draft_id: str
    revision_no: int = Field(ge=1)
    narrative: list[NarrativeSection] = Field(min_length=6, max_length=6)


class VerifyResponse(StrictModel):
    verification_id: str
    passed: bool
    status: VerifyStatus
    code_checks: list[CodeCheck]
    llm_checks: list[LlmCheck] | None
    verifier_version: str
    produced_at: Timestamp


# ---------- POST /v1/cases/summary (W4 말) ----------


class SummaryRequest(StrictModel):
    case_no: str
    alert: Alert
    transaction_ids: list[TransactionId] = Field(min_length=1)


class SummaryResponse(StrictModel):
    case_no: str
    facts: Facts
    summary_lines: list[str] = Field(min_length=1, max_length=6)
    model_focus: str | None = Field(default=None, description="'모델이 주목한 점' 한 줄 — 관측과 섞지 않음")
    code_checks: list[CodeCheck]
    generation_meta: GenerationMeta


DraftResponse.model_rebuild()
