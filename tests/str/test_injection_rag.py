"""SCRUM-125 활성 — 오류 주입 13 (RAG 실패) 전용 (docs/str/08 표).

`test_injection.py` 의 ACTIVE 목록에 13 이 들어감. 실제 통합 "코드 5 통과·AMOUNT_MATCH" 는 ★L live.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.application.draft_service import DraftService
from aml_ai.str.infrastructure.retriever import Retriever
from tests.conftest import FIXTURES, load_json


def _base_facts() -> Facts:
    return Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))


def test_injection_13_retrieval_unavailable_falls_back_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """오류 주입 13 — embedder 가 `RetrievalUnavailable` 던지면 **draft_service._references** 가
    그 분기에서 `[]` 로 폴백해 초안이 끝까지 돎.

    테스트는 try/except 로 위장하지 않음 — DraftService 실제 분기를 돌린다.
    통합(코드 5 통과·AMOUNT_MATCH 등)은 ★L live.
    """
    embedder = MagicMock(spec=EmbeddingClient)
    embedder.embed.side_effect = RetrievalUnavailable("embedding key missing")
    retriever = Retriever(session=MagicMock(), embedder=embedder, enabled=True)

    service = MagicMock(spec=DraftService)
    service.retriever = retriever

    warnings: list[tuple[str, dict]] = []
    import aml_ai.str.application.draft_service as mod

    class _LogSpy:
        def warning(self, msg: str, extra: dict | None = None) -> None:
            warnings.append((msg, dict(extra or {})))

    monkeypatch.setattr(mod, "log", _LogSpy())

    refs = DraftService._references(service, _base_facts())
    assert refs == []
    assert any(msg == "retrieval_unavailable" for msg, _ in warnings)
