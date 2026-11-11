"""임베딩 클라이언트 (RAG, W4). 멀티링구얼 1종. 실패는 RetrievalUnavailable — 호출자가 [] 로 진행."""

from __future__ import annotations

from typing import Protocol

import httpx
from pydantic import BaseModel, FiniteFloat, ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.str.domain.constants import EMBED_BATCH


class _EmbeddingItem(BaseModel):
    embedding: list[FiniteFloat]


class _EmbeddingResponse(BaseModel):
    data: list[_EmbeddingItem]


class EmbeddingClient(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HttpEmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @property
    def model(self) -> str:
        return self._s.embedding_model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self._s.embedding_model:
            raise RetrievalUnavailable("EMBEDDING_MODEL 빈 값")
        if not texts:
            return []
        if not self._s.llm_api_key:
            raise RetrievalUnavailable("embedding key missing")
        vectors: list[list[float]] = []
        try:
            with httpx.Client(timeout=self._s.llm_timeout_s) as client:
                for start in range(0, len(texts), EMBED_BATCH):
                    batch = texts[start : start + EMBED_BATCH]
                    response = client.post(
                        f"{self._s.llm_api_base.rstrip('/')}/embeddings",
                        json={"model": self._s.embedding_model, "input": batch},
                        headers={"Authorization": f"Bearer {self._s.llm_api_key}"},
                    )
                    response.raise_for_status()
                    parsed = _EmbeddingResponse.model_validate_json(response.content)
                    embeddings = [item.embedding for item in parsed.data]
                    if len(embeddings) != len(batch) or any(
                        len(vec) != self._s.embedding_dim for vec in embeddings
                    ):
                        raise RetrievalUnavailable("embedding shape mismatch")
                    vectors.extend(embeddings)
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise RetrievalUnavailable("embedding request failed") from exc
        return vectors


def make_embedding_client(settings: Settings) -> EmbeddingClient:
    return HttpEmbeddingClient(settings)
