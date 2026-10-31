"""규약 5절 — narrative (LLM 출력·응답·검증 요청 섹션). 정본 docs/str/05·06.

**섹션 집합 두 가지 공존** (SCRUM-47, 반영일 11/6):
- `SectionV1` 6개 — 기존.
- `SectionV2` 7개 — 별지 제1호 서술부(SUBJECT·DATE·PLACE·INSTRUMENT·METHOD·GROUNDS·OPINION, 서식 1~7).

이름이 겹치지 않아 **집합만 보고 버전을 안다** → 요청·응답에 버전 칸 없음(규약 JSON 모양 그대로).
공용 `Section = SectionV1 | SectionV2` 는 응답·검증 요청용. LLM 출력 스키마는 버전별 `NarrativeOutV1`·`V2`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from aml_ai.shared.schemas.common import StrictModel, TransactionId

NARRATIVE_TEXT_MAX = 1200


class SectionV1(StrEnum):
    """기존 6개 — 반영일 전 승인본·초안 보존용(docs/shared/01)."""

    SUMMARY = "SUMMARY"
    WHO = "WHO"
    WHAT_WHEN_WHERE = "WHAT_WHEN_WHERE"
    HOW = "HOW"
    WHY_SUSPICIOUS = "WHY_SUSPICIOUS"
    CONCLUSION = "CONCLUSION"


class SectionV2(StrEnum):
    """별지 제1호 서술부 7항목 — 서식 1~7 순서 (SCRUM-47 · 노션 6-1)."""

    SUBJECT = "SUBJECT"
    DATE = "DATE"
    PLACE = "PLACE"
    INSTRUMENT = "INSTRUMENT"
    METHOD = "METHOD"
    GROUNDS = "GROUNDS"
    OPINION = "OPINION"


SECTION_ORDER_V1: tuple[SectionV1, ...] = tuple(SectionV1)
SECTION_ORDER_V2: tuple[SectionV2, ...] = tuple(SectionV2)

Section = SectionV1 | SectionV2
"""공용 — 응답·검증 요청의 섹션 타입(두 집합 모두 수용). LLM 출력은 버전별 모델이 좁힌다."""


def section_set_version(sections: list[Section]) -> type[StrEnum]:
    """섹션 값 집합이 v1·v2 중 어느 쪽인지. 섞이거나 어느 쪽도 아니면 ValueError.

    해시(shared/hashing)와 검증(domain/verification) 이 같이 쓴다 — 집합이 결정하는 "버전".
    """
    values = {s.value for s in sections}
    if values == {e.value for e in SectionV1}:
        return SectionV1
    if values == {e.value for e in SectionV2}:
        return SectionV2
    raise ValueError(
        f"sections must be v1 ({len(SectionV1)}) or v2 ({len(SectionV2)}) set, not mixed/partial"
    )


def _each_section_once(sections: list[Section]) -> None:
    """집합이 v1 또는 v2 전체인지. 중복·누락·섞임 거부."""
    if len(sections) != len({s.value for s in sections}):
        raise ValueError("sections must be unique")
    section_set_version(sections)  # 어느 집합도 아니면 raise


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


class _LlmNarrativeV1(LlmNarrativeSection):
    """LLM 출력 스키마용 — v1 집합의 섹션 enum 만 노출(출력 스키마에 13개 안 보이게, SCRUM-47)."""

    section: SectionV1


class _LlmNarrativeV2(LlmNarrativeSection):
    """LLM 출력 스키마용 — v2 집합의 섹션 enum 만 노출."""

    section: SectionV2


class NarrativeOut(StrictModel):
    """검증·응답 공용 — 집합이 v1 6개 또는 v2 7개."""

    narrative: list[LlmNarrativeSection] = Field(min_length=len(SectionV1), max_length=len(SectionV2))

    @field_validator("narrative")
    @classmethod
    def _sections(cls, v: list[LlmNarrativeSection]) -> list[LlmNarrativeSection]:
        _each_section_once([s.section for s in v])
        return v


class NarrativeOutV1(StrictModel):
    """LLM 출력 스키마(v1) — enum 6개만 노출. 생성기가 활성 버전에 따라 고름."""

    narrative: list[_LlmNarrativeV1] = Field(min_length=len(SectionV1), max_length=len(SectionV1))

    @field_validator("narrative")
    @classmethod
    def _sections(cls, v: list[_LlmNarrativeV1]) -> list[_LlmNarrativeV1]:
        _each_section_once([s.section for s in v])
        return v


class NarrativeOutV2(StrictModel):
    """LLM 출력 스키마(v2) — enum 7개만 노출."""

    narrative: list[_LlmNarrativeV2] = Field(min_length=len(SectionV2), max_length=len(SectionV2))

    @field_validator("narrative")
    @classmethod
    def _sections(cls, v: list[_LlmNarrativeV2]) -> list[_LlmNarrativeV2]:
        _each_section_once([s.section for s in v])
        return v


class NarrativeSectionBase(StrictModel):
    """응답·검증 요청 섹션 공통(section·text·cites·evidence_ids) — SCRUM-46 ★A 2.

    `NarrativeSection`(응답, 1,200자 코드포인트) · `RevisedNarrativeSection`(검증, 5,000자 NFC·UTF-16)의
    공통 부모. 길이 제한은 자식에서 정의한다. `text` 는 strip 하지 않고 공백만 거부
    (docs/shared/01 해시 규칙 — 09_decisions SCRUM-16).
    """

    section: Section
    text: Annotated[str, StringConstraints(strip_whitespace=False, min_length=1)]
    cites: list[str] = Field(default_factory=list)
    evidence_ids: list[TransactionId] = Field(default_factory=list)

    @field_validator("text")
    @classmethod
    def _text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be whitespace-only")
        return v


class NarrativeSection(NarrativeSectionBase):
    """응답·초안 요청 섹션 — 1,200자 코드포인트 기준(LLM 출력 제약과 동일). evidence_ids 는 코드가 만든다."""

    text: Annotated[
        str,
        StringConstraints(strip_whitespace=False, min_length=1, max_length=NARRATIVE_TEXT_MAX),
    ]


class NarrativeRef(StrictModel):
    """검증 응답 narrative_refs — 검증한 본문 기준으로 다시 계산한 근거 (안건 23 세부 (a))."""

    section: Section
    cites: list[str]
    evidence_ids: list[TransactionId]
