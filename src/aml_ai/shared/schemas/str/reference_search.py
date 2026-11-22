"""참고 사례 검색 `POST /v1/references/search` 요청·응답 (SCRUM-309, docs/shared/01 "참고 사례 검색").

조회 전용 — 본문 칸 없음. 상태별 칸 규칙(FOUND ↔ 1건 이상 · EMPTY ↔ 0건 · score 내림차순)은 여기서 본다
(백엔드 `requireReferenceSearchResponse` 와 같은 규칙). 결과 수 ≤ top_k · 태그 겹침은 요청을 아는 서비스가 지킴.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from aml_ai.shared.schemas.common import StrictModel, SystemTimestamp, Typology
from aml_ai.shared.text import utf16_len_nfc

REFERENCE_QUERY_MAX = 200  # 설계 5.1 — NFC 뒤 UTF-16
REFERENCE_TOP_K_MAX = 10
REFERENCE_TOP_K_DEFAULT = 5
REFERENCE_TYPOLOGIES_MAX = 3
SEARCHABLE_TYPOLOGIES = frozenset(
    {Typology.FAN_IN, Typology.FAN_OUT, Typology.CYCLE, Typology.SCATTER_GATHER, Typology.GATHER_SCATTER}
)


class ReferenceSourceType(StrEnum):
    PUBLIC = "PUBLIC"
    APPROVED_STR = "APPROVED_STR"  # B(SCRUM-310) — 이번엔 요청에서 늘 거절


class ReferenceSearchStatus(StrEnum):
    FOUND = "FOUND"
    EMPTY = "EMPTY"


def _distinct(values: list) -> list:
    if len(set(values)) != len(values):
        raise ValueError("duplicate values")
    return values


class ReferenceSearchRequest(StrictModel):
    typologies: list[Typology] = Field(min_length=1, max_length=REFERENCE_TYPOLOGIES_MAX)
    query: Annotated[str, StringConstraints(strip_whitespace=False)] | None = None
    top_k: int = Field(default=REFERENCE_TOP_K_DEFAULT, ge=1, le=REFERENCE_TOP_K_MAX)
    source_types: list[ReferenceSourceType] = Field(
        default_factory=lambda: [ReferenceSourceType.PUBLIC], min_length=1
    )

    @field_validator("typologies")
    @classmethod
    def _searchable(cls, v: list[Typology]) -> list[Typology]:
        if not set(v) <= SEARCHABLE_TYPOLOGIES:
            raise ValueError("typology not searchable")
        return _distinct(v)

    @field_validator("query")
    @classmethod
    def _query(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.strip():
            raise ValueError("query must not be empty or whitespace-only")
        if utf16_len_nfc(v) > REFERENCE_QUERY_MAX:
            raise ValueError(f"query must be ≤{REFERENCE_QUERY_MAX} UTF-16 code units after NFC")
        return v

    @field_validator("source_types")
    @classmethod
    def _sources(cls, v: list[ReferenceSourceType]) -> list[ReferenceSourceType]:
        if ReferenceSourceType.APPROVED_STR in v:
            raise ValueError("APPROVED_STR is not enabled")
        return _distinct(v)


class ReferenceResult(StrictModel):
    doc_id: str
    doc_title: str
    publisher: str | None
    year: int | None
    page: int
    score: float = Field(ge=-1.0, le=1.0)  # cosine
    chunk_id: str
    typologies: list[Typology] = Field(min_length=1)
    source_type: ReferenceSourceType


class ReferenceSearchMeta(StrictModel):
    degraded: bool
    candidates: int = Field(ge=0)
    latency_ms: int = Field(ge=0)


class ReferenceSearchResponse(StrictModel):
    produced_at: SystemTimestamp
    status: ReferenceSearchStatus
    results: list[ReferenceResult] = Field(max_length=REFERENCE_TOP_K_MAX)
    retrieval_version: str = Field(min_length=1)
    search_meta: ReferenceSearchMeta

    @model_validator(mode="after")
    def _status_matches(self) -> ReferenceSearchResponse:
        if (self.status is ReferenceSearchStatus.FOUND) != bool(self.results):
            raise ValueError("FOUND needs results, EMPTY needs none")
        scores = [r.score for r in self.results]
        if scores != sorted(scores, reverse=True):
            raise ValueError("results must be sorted by score desc")
        return self
