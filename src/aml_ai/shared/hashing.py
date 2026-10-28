"""narrative 본문 해시 — 백엔드 NarrativeHash.java 와 같은 값 (docs/shared/01 "narrative 해시")."""

from __future__ import annotations

from aml_ai.shared.schemas.str import NarrativeSection


def narrative_sha256(narrative: list[NarrativeSection]) -> str:
    """섹션 고정 순서, section·text 만, NFC, 공백 없는 JSON, UTF-8 sha256 hex."""
    raise NotImplementedError("SCRUM-16 — docs/shared/01 해시 규칙 + contracts/examples/narrative_hash.json")
