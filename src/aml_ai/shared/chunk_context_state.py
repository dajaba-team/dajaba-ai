"""SCRUM-308-3 — 이 프로세스가 청크 맥락 새 표를 쓰는지(기동 검사 결과, str/10 "청크 맥락").

기동 검사가 통과해야만 True. 검사 전·끔·DB 접속 실패면 False — 그 프로세스는 재시작 전까지 지금 표(DB 가 살아나도).
"""

from __future__ import annotations

from aml_ai.shared.config import Settings

_verified = False


def set_verified(value: bool) -> None:
    global _verified  # noqa: PLW0603 — 프로세스 하나에 한 번(기동)
    _verified = value


def in_use(settings: Settings) -> bool:
    return settings.rag_chunk_context_active and _verified
