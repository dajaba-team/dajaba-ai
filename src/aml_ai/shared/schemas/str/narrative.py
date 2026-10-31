"""규약 5절 — narrative (LLM 출력·응답·검증 요청 섹션, 섹션 enum). 정본 docs/str/05·06."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from aml_ai.shared.schemas.common import StrictModel, TransactionId

NARRATIVE_TEXT_MAX = 1200


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
