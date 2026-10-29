"""규약 5절 — STR 초안·검증·요약. facts 와 narrative 의 정본 모양 (docs/str/04, 05, 06)."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.common import (
    AccountKey,
    CurrencyCode,
    FactAmount,
    Sha256Hex,
    StrictModel,
    Timestamp,
    TransactionId,
    Typology,
    TypologySource,
)
from aml_ai.shared.schemas.scores import Reason

INVESTIGATOR_NOTES_MAX = 2000  # AI 설계 7A 2번 — 메모 상한
NARRATIVE_TEXT_MAX = 1200
MODEL_SIGNALS_MAX = 3

# ---------- facts (docs/str/04) ----------


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


# ---------- narrative (docs/str/05) ----------


class Section(StrEnum):
    """고정 순서 = 해시 순서 (docs/shared/01). 서식 7항목 전환은 「STR 승인 이후·보고서 서식 회의 안건」 3·6-1."""

    SUMMARY = "SUMMARY"
    WHO = "WHO"
    WHAT_WHEN_WHERE = "WHAT_WHEN_WHERE"
    HOW = "HOW"
    WHY_SUSPICIOUS = "WHY_SUSPICIOUS"
    CONCLUSION = "CONCLUSION"


SECTION_ORDER: tuple[Section, ...] = tuple(Section)


def _each_section_once(sections: list[Section]) -> None:
    if sorted(sections) != sorted(Section):
        raise ValueError(f"each of the {len(Section)} sections exactly once")


class LlmNarrativeSection(StrictModel):
    """LLM 출력 한 섹션 — cites 는 fact 키. 거래 ID 는 LLM 이 고르지 않는다.

    `text` 는 strip 하지 않는다 — 본문 해시(shared/01)가 "앞뒤 공백 그대로"라 Java 와 어긋나면 안 됨.
    대신 공백만 있는 text 는 validator 로 거부(min_length=1 만으로는 "   " 통과).
    """

    section: Section
    text: Annotated[
        str,
        StringConstraints(strip_whitespace=False, min_length=1, max_length=NARRATIVE_TEXT_MAX),
    ]
    cites: list[str] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be whitespace-only")
        return v


class NarrativeOut(StrictModel):
    """LLM 출력 스키마. 섹션 enum 각 1회. cites ⊆ FACT_KEYS 는 facts 가 있어야 해서 생성기가 본다."""

    narrative: list[LlmNarrativeSection] = Field(min_length=len(Section), max_length=len(Section))

    @field_validator("narrative")
    @classmethod
    def _sections(cls, v: list[LlmNarrativeSection]) -> list[LlmNarrativeSection]:
        _each_section_once([s.section for s in v])
        return v


class NarrativeSection(LlmNarrativeSection):
    """응답·검증 요청의 섹션. evidence_ids = cites 의 fact 키 → 거래 ID 합집합 (코드가 만든다)."""

    evidence_ids: list[TransactionId] = Field(default_factory=list)


class NarrativeRef(StrictModel):
    """검증 응답 narrative_refs — 검증한 본문 기준으로 다시 계산한 근거 (안건 23 세부 (a))."""

    section: Section
    cites: list[str]
    evidence_ids: list[TransactionId]


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


# ---------- POST /v1/str/drafts (규약 5.1·5.2) ----------


class DraftRequest(StrictModel):
    draft_id: str = Field(description="백엔드가 호출 전 발급. 재전송은 같은 id, 재생성은 새 id")
    case_no: str
    alert: Alert
    evidence_transaction_ids: list[TransactionId] = Field(
        min_length=1, description="= alert.transaction_ids 전체. 점수 응답의 같은 이름 필드와 다르다"
    )
    reasons: list[Reason] = Field(description="3절 reasons 그대로. 점수가 없으면 []")
    prior_alert_count: int = Field(ge=0, description="건수만 — 내용은 보내지 않는다")
    investigator_notes: str | None = Field(max_length=INVESTIGATOR_NOTES_MAX)
    reporting_institution: str | None


class DraftResponse(StrictModel):
    draft_id: str
    generation_id: str
    facts: Facts
    narrative: list[NarrativeSection]
    generation_meta: GenerationMeta
    verification: None = Field(default=None, description="안건 17 — 항상 null, 검증은 /v1/str/verify")

    @field_validator("narrative")
    @classmethod
    def _sections(cls, v: list[NarrativeSection]) -> list[NarrativeSection]:
        _each_section_once([s.section for s in v])
        return v


# ---------- POST /v1/str/verify (규약 5.3, docs/str/06) ----------


class CodeCheckName(StrEnum):
    AMOUNT_MATCH = "AMOUNT_MATCH"
    DATE_MATCH = "DATE_MATCH"
    COUNT_MATCH = "COUNT_MATCH"
    ACCOUNT_ID_MATCH = "ACCOUNT_ID_MATCH"
    EVIDENCE_IN_SCOPE = "EVIDENCE_IN_SCOPE"


class CheckReason(StrEnum):
    """match=false 일 때만."""

    MISMATCH = "MISMATCH"
    UNPARSED = "UNPARSED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    MISSING = "MISSING"


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
    VERIFY_UNAVAILABLE = "VERIFY_UNAVAILABLE"  # 평가자 호출 실패 — 검증 실패가 아님 (안건 9)


class CodeCheck(StrictModel):
    check: CodeCheckName
    section: Section | None = Field(default=None, description="None = 초안 전체")
    draft_value: str | None
    source_value: str | None
    match: bool
    reason: CheckReason | None = None

    @model_validator(mode="after")
    def _reason_only_on_fail(self) -> CodeCheck:
        if self.match and self.reason is not None:
            raise ValueError("reason only when match=false")
        if not self.match and self.reason is None:
            raise ValueError("match=false needs a reason")
        return self


class LlmCheck(StrictModel):
    check: LlmCheckName
    comment: str = Field(max_length=500, description="score 보다 앞 — 평가자가 근거를 먼저 쓴다")
    score: int = Field(ge=1, le=5)


class JudgeOut(StrictModel):
    """judge LLM 출력 스키마. 5개, 각 1회."""

    checks: list[LlmCheck] = Field(min_length=len(LlmCheckName), max_length=len(LlmCheckName))

    @field_validator("checks")
    @classmethod
    def _each_check_once(cls, v: list[LlmCheck]) -> list[LlmCheck]:
        if sorted(c.check for c in v) != sorted(LlmCheckName):
            raise ValueError("each of the 5 checks exactly once")
        return v


class VerifyRequest(StrictModel):
    generation_id: str = Field(description="어느 생성본의 facts 와 대조하나")
    revision_no: int = Field(ge=1, description="백엔드 str_revisions 번호. 1 = AI 원문")
    narrative: list[NarrativeSection] = Field(min_length=len(Section), max_length=len(Section))

    @field_validator("narrative")
    @classmethod
    def _sections(cls, v: list[NarrativeSection]) -> list[NarrativeSection]:
        _each_section_once([s.section for s in v])
        return v


class VerifyResponse(StrictModel):
    verification_id: str
    generation_id: str
    revision_no: int = Field(ge=1)
    narrative_sha256: Sha256Hex = Field(description="검사한 본문 해시 — ApprovalGate 기준 (shared/01)")
    passed: bool
    status: VerifyStatus
    code_checks: list[CodeCheck]
    llm_checks: list[LlmCheck] | None
    narrative_refs: list[NarrativeRef] | None = Field(description="평가자를 안 돌린 경우 null")
    verifier_version: str
    produced_at: Timestamp

    @model_validator(mode="after")
    def _passed_matches_status(self) -> VerifyResponse:
        if self.passed != (self.status is VerifyStatus.PASSED):
            raise ValueError("passed must be true exactly when status=PASSED")
        return self


# ---------- POST /v1/cases/summary (W4 말) ----------


class SummaryRequest(StrictModel):
    case_no: str
    alert: Alert
    evidence_transaction_ids: list[TransactionId] = Field(min_length=1)


class SummaryResponse(StrictModel):
    case_no: str
    facts: Facts
    summary_lines: list[str] = Field(min_length=1, max_length=6)
    model_focus: str | None = Field(default=None, description="'모델이 주목한 점' 한 줄 — 관측과 섞지 않음")
    code_checks: list[CodeCheck]
    generation_meta: GenerationMeta
