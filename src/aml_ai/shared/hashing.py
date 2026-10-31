"""narrative 본문 해시 — 백엔드 NarrativeHash.java 와 같은 값 (docs/shared/01 "narrative 해시")."""

from __future__ import annotations

import hashlib
import json
import unicodedata

from aml_ai.shared.schemas.str import SECTION_ORDER, NarrativeSectionBase, Section


def narrative_sha256(narrative: list[NarrativeSectionBase]) -> str:
    """섹션 고정 순서, section·text 만, NFC, 공백 없는 JSON, UTF-8 sha256 hex 소문자 64자.

    섹션 6개가 각각 한 번씩이 아니면 ValueError (docs/shared/01, 09_decisions 10/29).
    오류 메시지에는 섹션 이름·개수만. 본문(`text`)은 넣지 않는다 — 로그 금지 규칙.
    """
    _check_sections([s.section for s in narrative])
    by_section = {s.section: s for s in narrative}
    canonical = [
        {"section": sec.value, "text": unicodedata.normalize("NFC", by_section[sec].text)}
        for sec in SECTION_ORDER
    ]
    body = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _check_sections(sections: list[Section]) -> None:
    expected = set(SECTION_ORDER)
    got = set(sections)
    if len(sections) != len(SECTION_ORDER) or got != expected:
        missing = sorted(s.value for s in expected - got)
        extra = sorted(s.value for s in got - expected)
        duplicate = sorted({s.value for s in sections if sections.count(s) > 1})
        raise ValueError(
            f"narrative sections must be each of {len(SECTION_ORDER)} exactly once "
            f"(got {len(sections)}; missing={missing}; extra={extra}; duplicate={duplicate})"
        )
