"""규약 5.1·5.2 — POST /v1/str/drafts 요청·응답. 정본 docs/str/03·05."""

from __future__ import annotations

from pydantic import Field, field_validator

from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.common import StrictModel, SystemTimestamp, TransactionId
from aml_ai.shared.schemas.scores import Reason
from aml_ai.shared.schemas.str.facts import Facts
from aml_ai.shared.schemas.str.narrative import NarrativeSection, _each_section_once

INVESTIGATOR_NOTES_MAX = 2000  # AI 설계 7A 2번 — 메모 상한


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
