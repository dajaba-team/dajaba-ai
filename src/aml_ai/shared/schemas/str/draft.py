"""규약 5.1·5.2 — POST /v1/str/drafts 요청·응답. 정본 docs/str/03·05."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.common import StrictModel, SystemTimestamp, TransactionId
from aml_ai.shared.schemas.scores import Reason
from aml_ai.shared.schemas.str.facts import Facts
from aml_ai.shared.schemas.str.facts_input import FactsInput
from aml_ai.shared.schemas.str.narrative import NarrativeSection, _each_section_once
from aml_ai.shared.schemas.str.verify import LlmCheckName

INVESTIGATOR_NOTES_MAX = 2000  # AI 설계 7A 2번 — 메모 상한

RewriteSkipReason = Literal[
    "not_triggered",  # 평가자 전부 ≥ JUDGE_PASS_SCORE → 고쳐 쓰기 안 함
    "code_failed",  # 원본 코드 검사 실패 → 평가자 안 부름
    "critique_error",  # 평가자 예외 (LlmUnavailable·LlmInvalidOutput·기타)
    "budget",  # 남은 예산 < LLM_TIMEOUT_S (평가자 앞·고쳐 쓰기 앞 공용)
    "schema",  # 고쳐 쓰기 스키마 실패 (재생성 없음)
    "rewrite_error",  # 고쳐 쓰기 호출 연결·타임아웃·BudgetExceeded·기타
    "rewrite_code_failed",  # 고친 본문 코드 검사 실패
]


class Reference(StrictModel):
    """RAG 참고 사례 (docs/str/10). 응답 generation_meta.references."""

    doc_id: str
    doc_title: str
    page: int
    score: float
    text: str | None = Field(default=None, max_length=600, description="프롬프트용. 응답에는 보통 생략")


class RewriteMeta(StrictModel):
    """SCRUM-147 — 초안 생성 안 작성자–비평가 고쳐 쓰기 1회의 결과 메타.

    `attempted` = "고쳐 쓰기 LLM 호출을 실제로 보냈는가". 평가자만 돈 건 attempted=false.
    `critique_*` 는 평가자 호출 결과(초안 안 평가자 — 검증 결과 아님, verification=null 유지).
    """

    attempted: bool = False
    applied: bool = False
    skipped_reason: RewriteSkipReason | None = None
    critique_llm_model: str | None = None  # LlmResult.model 그대로. 평가자 호출 안 보냈으면 None
    critique_scores: dict[LlmCheckName, int] | None = None
    critique_tokens_in: int | None = None
    critique_tokens_out: int | None = None
    critique_latency_ms: int | None = None

    @model_validator(mode="after")
    def _applied_true_skipped_reason_must_be_none(self) -> RewriteMeta:
        if self.applied and self.skipped_reason is not None:
            raise ValueError("applied=True 이면 skipped_reason 은 None 이어야 한다")
        return self


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
    rewrite: RewriteMeta | None = None  # SCRUM-147 — 선택, 옛 저장 응답(ClaimReuse) 하위 호환


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

    def to_facts_input(self) -> FactsInput:
        """build_facts 공통 입력으로 (SCRUM-129 ★A 1). 라운드트립 테스트가 초안 녹화 키 보존을 보장."""
        return FactsInput(
            alert=self.alert,
            evidence_transaction_ids=self.evidence_transaction_ids,
            reasons=self.reasons,
            prior_alert_count=self.prior_alert_count,
            reporting_institution=self.reporting_institution,
        )


class DraftResponse(StrictModel):
    produced_at: SystemTimestamp
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
