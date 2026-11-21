"""임베딩 클라이언트 (RAG, W4). 멀티링구얼 1종. 실패는 RetrievalUnavailable — 호출자가 [] 로 진행."""

from __future__ import annotations

from typing import Protocol

import httpx
from pydantic import BaseModel, FiniteFloat, ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import EmbeddingIndexInvalid, EmbeddingModelMismatch, RetrievalUnavailable
from aml_ai.str.domain.constants import EMBED_BATCH


class _EmbeddingItem(BaseModel):
    embedding: list[FiniteFloat]
    index: int | None = None  # 입력 위치 — 응답 배열 순서를 믿지 않음(검토 5)


class _EmbeddingResponse(BaseModel):
    data: list[_EmbeddingItem]
    model: str | None = None  # 응답한 모델(SCRUM-308-2 판정 하네스가 DB 모델과 대조) — 없으면 None


class EmbeddingClient(Protocol):
    @property
    def model(self) -> str: ...  # 검색 SQL 이 같은 모델 행만 봄(검토 5)

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HttpEmbeddingClient:
    """배치마다 응답 `model`(strip) = 요청 모델(strip)일 때만 벡터를 돌려줌 — 다르거나 없으면 `EmbeddingModelMismatch`
    (`RetrievalUnavailable` 하위: 운영 Retriever 는 기존 임베딩 실패처럼 RAG 없이, 적재 도구는 INSERT 전 중단 — SCRUM-308-2 검토 4).
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    @property
    def model(self) -> str:
        return self._s.embedding_model.strip()  # 요청·대조·DB 기록이 같은 정규화 값

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.model:
            raise RetrievalUnavailable("EMBEDDING_MODEL 빈 값")
        if not texts:
            return []
        if not self._s.llm_api_key:
            raise RetrievalUnavailable("embedding key missing")
        vectors: list[list[float]] = []
        try:
            with httpx.Client(timeout=self._s.llm_timeout_s) as client:
                for start in range(0, len(texts), EMBED_BATCH):
                    vectors.extend(self._batch(client, texts[start : start + EMBED_BATCH]))
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise RetrievalUnavailable("embedding request failed") from exc
        return vectors

    def _batch(self, client: httpx.Client, batch: list[str]) -> list[list[float]]:
        response = client.post(
            f"{self._s.llm_api_base.rstrip('/')}/embeddings",
            json={"model": self.model, "input": batch},
            headers={"Authorization": f"Bearer {self._s.llm_api_key}"},
        )
        response.raise_for_status()
        parsed = _EmbeddingResponse.model_validate_json(response.content)
        if (parsed.model or "").strip() != self.model:
            raise EmbeddingModelMismatch("embedding model mismatch")
        if len(parsed.data) != len(batch) or any(
            len(i.embedding) != self._s.embedding_dim for i in parsed.data
        ):
            raise RetrievalUnavailable("embedding shape mismatch")
        return _in_input_order(parsed.data)


def _in_input_order(items: list[_EmbeddingItem]) -> list[list[float]]:
    """응답 `index` 로 입력 순서 복원 — 0..n-1 순열이어야(단일 입력은 index 없으면 0). 아니면 `EmbeddingIndexInvalid`."""
    indexes = [0 if i.index is None and len(items) == 1 else i.index for i in items]
    if None in indexes or sorted(indexes) != list(range(len(items))):  # type: ignore[type-var]
        raise EmbeddingIndexInvalid("embedding index invalid")
    return [item.embedding for _, item in sorted(zip(indexes, items, strict=True), key=lambda p: p[0])]


def make_embedding_client(settings: Settings) -> EmbeddingClient:
    from aml_ai.shared.infrastructure.tracing import wrap_embedding_client

    return wrap_embedding_client(HttpEmbeddingClient(settings), settings)
