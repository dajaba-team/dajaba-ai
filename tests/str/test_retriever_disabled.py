"""SCRUM-125 — RAG_ENABLED=false 면 Retriever 는 embed·DB 를 안 부름 (INTENT ★A 7, 녹화·CI 안정).

- `Retriever(enabled=False).retrieve(facts)` → `[]` + embed 호출 0
- 기본값 `rag_enabled=False` 유지 (shared/config.Settings default) — 녹화 통합 테스트 재현성

develop 에서 통과 (회귀): `_enabled=False` 분기는 이미 있음. 활성 뒤에도 꺼지면 호출 0 이어야 함.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.retriever import Retriever


def test_disabled_returns_empty_without_calls(mixed: Facts) -> None:
    """RAG off — retrieve() 가 바로 [] 반환, embed 는 한 번도 안 불림."""
    embedder = MagicMock(spec=EmbeddingClient)
    retriever = Retriever(
        session=cast("object", None),  # type: ignore[arg-type]  # 호출 안 됨 — None 통과
        embedder=embedder,
        enabled=False,
    )
    result = retriever.retrieve(mixed)
    assert result == []
    embedder.embed.assert_not_called()


def test_default_rag_enabled_is_false_in_settings() -> None:
    """shared/config.Settings — rag_enabled 기본 False (녹화·CI 안정)."""
    from aml_ai.shared.config import Settings

    # .env 파일 영향 없이 기본값만 — env_file 미사용 경로
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.rag_enabled is False


def test_disabled_does_not_touch_db_session(mixed: Facts) -> None:
    """꺼진 Retriever 는 session 메서드 호출 0 — session=None 으로도 안전."""
    session = MagicMock()
    embedder = MagicMock(spec=EmbeddingClient)
    retriever = Retriever(session=session, embedder=embedder, enabled=False)
    assert retriever.retrieve(mixed) == []
    # session 어떤 메서드도 안 불림
    assert not session.method_calls


@pytest.fixture
def mixed_with_typology(mixed: Facts) -> Facts:
    """유형 FAN_IN 로 바꿔 둠 — 활성 경로에서도 enable=False 면 호출 0 확인용."""
    from aml_ai.shared.schemas.common import Typology

    return mixed.model_copy(update={"typology": Typology.FAN_IN})


def test_disabled_with_valid_typology_still_skips(mixed_with_typology: Facts) -> None:
    """유형이 있어도 enabled=False 면 바로 []."""
    embedder = MagicMock(spec=EmbeddingClient)
    retriever = Retriever(
        session=cast("object", None),  # type: ignore[arg-type]
        embedder=embedder,
        enabled=False,
    )
    assert retriever.retrieve(mixed_with_typology) == []
    embedder.embed.assert_not_called()
