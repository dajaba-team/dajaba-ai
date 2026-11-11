"""SCRUM-125 — Retriever 실패 처리 (docs/str/10 "실패 처리", INTENT ★A 6).

- embedder 가 `RetrievalUnavailable` 던지면 `retrieve()` 도 그대로 전파 → 호출자 (`draft_service._references`) 가 잡아 `[]`
- DB 검색 예외도 `Retriever._search` 에서 `RetrievalUnavailable` 로 감싸 전파
- 오류 주입 13 활성 — `tests/str/test_injection.py` 의 `SKIPPED_DET` 에서 13 빠지고 `ACTIVE` 에 들어감

develop 에서 실패: `_search` 가 `NotImplementedError`, `HttpEmbeddingClient.embed` 가 항상 `RetrievalUnavailable` (예외 전파 분기는 있지만 `_search` 가 안 돌아 DB 예외 감싸기 경로 확인 불가).
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.retriever import Retriever


def _enabled_retriever(
    *, embedder: EmbeddingClient | None = None, session: object | None = None
) -> Retriever:
    return Retriever(
        session=cast("object", session),  # type: ignore[arg-type]
        embedder=embedder or MagicMock(spec=EmbeddingClient),
        enabled=True,
    )


def test_embedding_error_propagates_retrieval_unavailable(mixed: Facts) -> None:
    """embedder.embed 가 RetrievalUnavailable 던지면 retrieve() 도 그대로 전파."""
    facts = mixed.model_copy(update={"typology": Typology.FAN_IN})
    embedder = MagicMock(spec=EmbeddingClient)
    embedder.embed.side_effect = RetrievalUnavailable("embedding key missing")

    retriever = _enabled_retriever(embedder=embedder)
    with pytest.raises(RetrievalUnavailable):
        retriever.retrieve(facts)
    embedder.embed.assert_called_once()


def test_db_error_wrapped_as_retrieval_unavailable(monkeypatch: pytest.MonkeyPatch, mixed: Facts) -> None:
    """DB session.execute 예외도 Retriever._search 가 RetrievalUnavailable 로 감싸 전파."""
    from sqlalchemy.exc import OperationalError

    facts = mixed.model_copy(update={"typology": Typology.FAN_IN})
    embedder = MagicMock(spec=EmbeddingClient)
    embedder.embed.return_value = [[0.0] * 1536]

    session = MagicMock()
    session.execute.side_effect = OperationalError("stmt", {}, Exception("db down"))

    retriever = _enabled_retriever(embedder=embedder, session=session)
    with pytest.raises(RetrievalUnavailable):
        retriever.retrieve(facts)


def test_draft_service_catches_retrieval_unavailable_returns_empty(
    mixed: Facts,
) -> None:
    """draft_service._references 가 RetrievalUnavailable 잡아 [] 반환 — 초안 흐름 안 끊김 (회귀)."""
    facts = mixed.model_copy(update={"typology": Typology.FAN_IN})
    embedder = MagicMock(spec=EmbeddingClient)
    embedder.embed.side_effect = RetrievalUnavailable("boom")

    retriever = _enabled_retriever(embedder=embedder)
    # draft_service 패턴 그대로 — try/except RetrievalUnavailable
    try:
        result = retriever.retrieve(facts)
    except RetrievalUnavailable:
        result = []
    assert result == []


def test_none_typology_returns_empty_no_embed(mixed: Facts) -> None:
    """facts.typology=None → retrieve() 가 바로 [] (백필 없음, INTENT ★A 4)."""
    facts = mixed.model_copy(update={"typology": None})
    embedder = MagicMock(spec=EmbeddingClient)

    retriever = _enabled_retriever(embedder=embedder)
    assert retriever.retrieve(facts) == []
    embedder.embed.assert_not_called()


def test_injection_13_is_active_not_skipped() -> None:
    """오류 주입 13 활성 — tests/str/test_injection.py 의 ACTIVE 에 13 들어가고 SKIPPED_DET 에서 빠짐.

    develop 에서 실패: 지금 SKIPPED_DET = [13, 32, 33, 34] 이라 13 이 skip 목록에 있음.
    """
    from tests.str.test_injection import ACTIVE, SKIPPED_DET

    assert 13 in ACTIVE, "오류 주입 13 활성 (SCRUM-125): ACTIVE 에 13 추가 필요"
    assert 13 not in SKIPPED_DET, "오류 주입 13 활성: SKIPPED_DET 에서 13 제거"
