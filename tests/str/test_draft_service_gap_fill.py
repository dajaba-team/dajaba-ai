"""SCRUM-275 — DraftService 가 빈칸 채우기를 v4 + 스위치 켬일 때만 Retriever 에 넘김 (docs/str/10 "빈칸만 채우기")."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aml_ai.shared.config import Settings
from aml_ai.str.application import draft_service as mod
from aml_ai.str.application.draft_service import DraftService
from aml_ai.str.infrastructure.keyword_search import HttpKeywordSearch


def _build(**env: object) -> DraftService:
    return DraftService.build(MagicMock(), Settings(_env_file=None, RAG_ENABLED=True, **env))


def test_default_build_is_off() -> None:
    retriever = _build().retriever
    assert retriever._gap_fill is False and retriever._keyword is None  # noqa: SLF001


def test_v4_and_switch_on_wires_keyword_and_release(monkeypatch: pytest.MonkeyPatch) -> None:
    released: list[object] = []
    monkeypatch.setattr(mod, "end_read", released.append)
    session = MagicMock()
    svc = DraftService.build(session, Settings(_env_file=None, RAG_ENABLED=True, RAG_GAP_FILL_ENABLED=True))
    retriever = svc.retriever
    assert retriever._gap_fill is True  # noqa: SLF001
    assert isinstance(retriever._keyword, HttpKeywordSearch)  # noqa: SLF001
    retriever._release()  # noqa: SLF001
    assert released == [session]  # release = end_read(session) — SCRUM-122


@pytest.mark.parametrize("prompt", ["narrative_v2", "narrative_v3"])
def test_v2_v3_never_fill(prompt: str) -> None:
    retriever = _build(RAG_GAP_FILL_ENABLED=True, NARRATIVE_PROMPT=prompt).retriever
    assert retriever._gap_fill is False and retriever._keyword is None  # noqa: SLF001
