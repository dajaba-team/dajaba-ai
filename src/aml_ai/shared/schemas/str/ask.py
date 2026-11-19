"""규약 §5.4 제안 — POST /v1/cases/ask 요청·응답. 정본 docs/shared/01 (SCRUM-288)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from aml_ai.shared.schemas.common import StrictModel, SystemTimestamp, TransactionId
from aml_ai.shared.schemas.str.summary import SummaryRequest
from aml_ai.shared.schemas.str.verify import CodeCheck
from aml_ai.shared.text import utf16_len_nfc

ASK_QUESTION_MAX = 300  # 질문 ≤300자 — 설계 문서 5.2
ASK_ANSWER_MAX = 400  # 답 ≤400자 — 설계 문서 6.3
ASK_BUNDLES_MAX = 3  # 묶음 최대 3개 — 설계 문서 6.1


class AskStatus(StrEnum):
    ANSWERED = "ANSWERED"
    NO_DATA = "NO_DATA"
    UNVERIFIED = "UNVERIFIED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class AskKind(StrEnum):
    FACT = "FACT"
    WHY = "WHY"


class OutOfScopeReason(StrEnum):
    EDIT_REQUEST = "EDIT_REQUEST"
    OUTSIDE_CASE = "OUTSIDE_CASE"
    JUDGMENT = "JUDGMENT"


class AskRequest(SummaryRequest):
    """요약과 같은 입력 + question — 근거 부분집합 검사는 서비스에서 (docs/shared/01)."""

    question: Annotated[str, StringConstraints(strip_whitespace=False)]

    @field_validator("question")
    @classmethod
    def _question_within_limit(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be whitespace-only")
        if utf16_len_nfc(v) > ASK_QUESTION_MAX:
            raise ValueError(f"question must be ≤{ASK_QUESTION_MAX} UTF-16 code units after NFC")
        return v


class AskGenerationMeta(StrictModel):
    """계획+답 두 호출 합계 — OUT_OF_SCOPE 는 계획 호출분만 (docs/shared/01)."""

    llm_model: str
    prompt_version: str | None
    plan_prompt_version: str
    bundles: list[str] = Field(max_length=ASK_BUNDLES_MAX)
    server_version: str
    tokens_in: int
    tokens_out: int
    latency_ms: int

    @field_validator("bundles")
    @classmethod
    def _bundles_nonblank_unique(cls, v: list[str]) -> list[str]:
        if any(not item.strip() for item in v):
            raise ValueError("bundles must not contain blank strings")
        if len(v) != len(set(v)):
            raise ValueError("bundles must not contain duplicates")
        return v


class AskResponse(StrictModel):
    """질문 답변 응답 — 상태별 칸·코드 검사·답 프롬프트와 묶음 규칙 (SCRUM-288).

    answer 는 앞뒤 공백을 보존하고 길이만 NFC·UTF-16 으로 센다.
    ANSWERED 의 evidence_ids 는 거래가 안 달리는 fact 키를 위해 빈 목록도 허용한다.
    """

    produced_at: SystemTimestamp
    case_no: str
    generation_id: str
    status: AskStatus
    kind: AskKind | None
    out_of_scope_reason: OutOfScopeReason | None
    answer: Annotated[str, StringConstraints(strip_whitespace=False)] | None
    cites: list[str]
    evidence_ids: list[TransactionId]
    code_checks: list[CodeCheck]
    generation_meta: AskGenerationMeta

    @field_validator("cites")
    @classmethod
    def _cites_nonblank_unique(cls, v: list[str]) -> list[str]:
        if any(not item.strip() for item in v):
            raise ValueError("cites must not contain blank strings")
        if len(v) != len(set(v)):
            raise ValueError("cites must not contain duplicates")
        return v

    @field_validator("answer")
    @classmethod
    def _answer_within_limit(cls, v: str | None) -> str | None:
        if v is not None:
            if not v.strip():
                raise ValueError("answer must not be whitespace-only")
            if utf16_len_nfc(v) > ASK_ANSWER_MAX:
                raise ValueError(f"answer must be ≤{ASK_ANSWER_MAX} UTF-16 code units after NFC")
        return v

    @model_validator(mode="after")
    def _fields_match_status(self) -> AskResponse:
        if self.status is AskStatus.OUT_OF_SCOPE:
            if self.kind is not None or self.out_of_scope_reason is None:
                raise ValueError("OUT_OF_SCOPE needs kind=null and an out_of_scope_reason")
        elif self.kind is None or self.out_of_scope_reason is not None:
            raise ValueError("in-scope status needs a kind and out_of_scope_reason=null")

        if self.status is AskStatus.ANSWERED:
            if self.answer is None or not self.cites:
                raise ValueError("ANSWERED needs an answer and at least one cite")
        elif self.answer is not None or self.cites or self.evidence_ids:
            raise ValueError("non-ANSWERED status needs answer=null, cites=[], evidence_ids=[]")
        return self

    @model_validator(mode="after")
    def _checks_match_status(self) -> AskResponse:
        has_mismatch = any(not check.match for check in self.code_checks)
        if self.status is AskStatus.ANSWERED:
            if has_mismatch:
                raise ValueError("ANSWERED needs all code_checks to match")
        elif self.status is AskStatus.UNVERIFIED:
            if not has_mismatch:
                raise ValueError("UNVERIFIED needs at least one failed code_check")
        elif self.code_checks:
            raise ValueError("NO_DATA and OUT_OF_SCOPE need code_checks=[]")
        return self

    @model_validator(mode="after")
    def _meta_matches_status(self) -> AskResponse:
        meta = self.generation_meta
        if self.status is AskStatus.OUT_OF_SCOPE:
            if meta.prompt_version is not None or meta.bundles:
                raise ValueError("OUT_OF_SCOPE needs prompt_version=null and bundles=[]")
        elif meta.prompt_version is None or not meta.bundles:
            raise ValueError("in-scope status needs a prompt_version and at least one bundle")
        return self
