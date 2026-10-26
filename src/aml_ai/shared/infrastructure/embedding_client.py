"""임베딩 클라이언트 (RAG, W4). 멀티링구얼 1종. 실패는 RetrievalUnavailable — 호출자가 [] 로 진행."""

from __future__ import annotations

from typing import Protocol

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import RetrievalUnavailable


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HttpEmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def embed(self, texts: list[str]) -> list[list[float]]:
        # TODO(W4): provider 호출, 배치 64, 차원 = settings.embedding_dim 검증
        raise RetrievalUnavailable("embedding client not implemented (W4)")


def make_embedding_client(settings: Settings) -> EmbeddingClient:
    return HttpEmbeddingClient(settings)
