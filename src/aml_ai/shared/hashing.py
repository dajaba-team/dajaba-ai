"""narrative 본문 해시 — 백엔드 NarrativeHash.java 와 같은 값 (docs/shared/01 "narrative 해시").

**섹션 집합 두 가지 공존** (SCRUM-47) — 집합이 v1 6개면 v1 순서, v2 7개면 v2 순서로 정렬.
섞이거나 어느 쪽도 아니면 ValueError.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from enum import StrEnum

from aml_ai.shared.schemas.str import (
    SECTION_ORDER_V1,
    SECTION_ORDER_V2,
    NarrativeSectionBase,
    Section,
    SectionV1,
    section_set_version,
)


def narrative_sha256(narrative: list[NarrativeSectionBase]) -> str:
    """집합 보고 순서 선택, section·text 만, NFC, 공백 없는 JSON, UTF-8 sha256 hex 소문자 64자.

    집합이 v1·v2 어느 쪽도 아니거나 중복·누락이면 ValueError (docs/shared/01, SCRUM-47).
    오류 메시지에는 섹션 이름·개수만. 본문(`text`)은 넣지 않는다 — 로그 금지 규칙.
    """
    sections = [s.section for s in narrative]
    _check_sections(sections)
    order = _order_for(section_set_version(sections))
    by_section = {s.section.value: s for s in narrative}
    canonical = [
        {"section": sec.value, "text": unicodedata.normalize("NFC", by_section[sec.value].text)}
        for sec in order
    ]
    body = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _order_for(version: type[StrEnum]) -> tuple[StrEnum, ...]:
    return SECTION_ORDER_V1 if version is SectionV1 else SECTION_ORDER_V2


def _check_sections(sections: list[Section]) -> None:
    """중복·누락·섞임을 집합 검증과 함께 자세한 오류 메시지로 보고 (SCRUM-47)."""
    values = [s.value for s in sections]
    if len(values) == len(set(values)):
        return  # 중복 없음 — section_set_version 이 집합 검증
    duplicate = sorted({v for v in values if values.count(v) > 1})
    raise ValueError(f"narrative sections duplicated: {duplicate}")
