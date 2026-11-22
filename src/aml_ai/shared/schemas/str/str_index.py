"""승인 STR 색인 `POST /v1/references/str` 요청·응답 (SCRUM-310, docs/shared/01 "승인 STR 색인").

섹션은 7항목(`SectionV2`) 또는 옛 6섹션(`SectionV1`) 한 세트만 — 섞이면·같은 섹션 두 번이면 400.
응답 상태별 칸 규칙: INDEXED ↔ skip_reason null·chunk_count ≥ 1·retrieval_version 있음 / SKIPPED ↔ 이유·0.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from aml_ai.shared.schemas.common import StrictModel, SystemTimestamp, Typology
from aml_ai.shared.schemas.str.narrative import SectionV1, SectionV2

DRAFT_ID_MAX = 64  # ai.generations.draft_id String(64)
REPORT_NO_PATTERN = (
    r"^STR-[0-9]{4}-[0-9]{6}$"  # ASCII 숫자만(전각 숫자로 같은 번호가 따로 잠기지 않게, 추가 검토 1)
)
STR_INDEX_TYPOLOGIES_MAX = 3
STR_INDEX_TEXT_MAX = (
    5000  # SCRUM-361 — 백엔드 단락 상한과 같음. AI 가 ≤1200 청크로 나눔(초안 NARRATIVE_TEXT_MAX 1200 과 따로)
)
_V1 = frozenset(s.value for s in SectionV1)
_V2 = frozenset(s.value for s in SectionV2)


class StrIndexStatus(StrEnum):
    INDEXED = "INDEXED"
    SKIPPED = "SKIPPED"


class StrIndexSkipReason(StrEnum):
    RAW_ACCOUNT = "RAW_ACCOUNT"
    TOO_SHORT = "TOO_SHORT"
    DISABLED = "DISABLED"
    NO_FACTS = "NO_FACTS"  # `draft_id` 의 초안 facts 가 AI 에 없음(목업 모드 초안 등) — 케이스 계좌 대조 못 함(추가 검토 2)


class StrIndexSection(StrictModel):
    section: str
    text: Annotated[
        str, StringConstraints(strip_whitespace=False, min_length=1, max_length=STR_INDEX_TEXT_MAX)
    ]

    @field_validator("section")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in _V1 | _V2:
            raise ValueError("unknown section")
        return v


class StrIndexRequest(StrictModel):
    report_no: Annotated[str, StringConstraints(pattern=REPORT_NO_PATTERN)]
    draft_id: str = Field(
        min_length=1,
        max_length=DRAFT_ID_MAX,
        description="승인된 초안의 id — 그 초안 facts 로 케이스 계좌 대조",
    )
    approved_at: SystemTimestamp
    typologies: list[Typology] = Field(default_factory=list, max_length=STR_INDEX_TYPOLOGIES_MAX)
    sections: list[StrIndexSection] = Field(min_length=1)

    @field_validator("typologies")
    @classmethod
    def _distinct_typologies(cls, v: list[Typology]) -> list[Typology]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate typologies")
        return v

    @model_validator(mode="after")
    def _one_set(self) -> StrIndexRequest:
        names = [s.section for s in self.sections]
        if len(set(names)) != len(names):
            raise ValueError("duplicate section")
        if not (set(names) <= _V1 or set(names) <= _V2):
            raise ValueError("mixed section sets")
        return self

    @property
    def section_set(self) -> str:
        return "V2" if self.sections[0].section in _V2 else "V1"


class StrIndexResponse(StrictModel):
    produced_at: SystemTimestamp
    report_no: str
    status: StrIndexStatus
    skip_reason: StrIndexSkipReason | None
    chunk_count: int = Field(ge=0)
    retrieval_version: str | None = Field(
        description="DISABLED 면 null 일 수 있음(꺼져 있으면 모델·manifest 를 안 봄)"
    )

    @model_validator(mode="after")
    def _status_fields(self) -> StrIndexResponse:
        if self.status is StrIndexStatus.INDEXED:
            if self.skip_reason is not None or self.chunk_count < 1 or not self.retrieval_version:
                raise ValueError("INDEXED needs no skip_reason, chunk_count >= 1, retrieval_version")
        elif self.skip_reason is None or self.chunk_count != 0:
            raise ValueError("SKIPPED needs skip_reason and chunk_count 0")
        return self
