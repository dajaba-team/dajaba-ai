"""규약 5.3 — POST /v1/str/verify 요청·응답. 정본 docs/str/03·06."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from aml_ai.shared.schemas.common import Sha256Hex, StrictModel, SystemTimestamp
from aml_ai.shared.schemas.str.narrative import (
    NarrativeRef,
    NarrativeSection,
    Section,
    _each_section_once,
)


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
    produced_at: SystemTimestamp

    @model_validator(mode="after")
    def _passed_matches_status(self) -> VerifyResponse:
        if self.passed != (self.status is VerifyStatus.PASSED):
            raise ValueError("passed must be true exactly when status=PASSED")
        return self
