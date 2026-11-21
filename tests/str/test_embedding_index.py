"""SCRUM-308-2 추가 검토 5 — 임베딩 응답 `index` 로 입력 순서 복원 · 누락·중복·범위 밖이면 `EmbeddingIndexInvalid`
(적재 INSERT 0 · 운영 검색은 RAG 없이). 단일 입력은 index 없어도 0 으로 봄(기존 호환)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest
from tools.corpus_chunks import Chunk
from tools.ingest_corpus import _insert_chunks

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import EmbeddingIndexInvalid, RetrievalUnavailable
from aml_ai.shared.infrastructure import embedding_client as ec
from aml_ai.shared.infrastructure.embedding_client import HttpEmbeddingClient

EMB = Settings(_env_file=None, LLM_API_KEY="k", AI_LLM_MOCK=False, EMBEDDING_MODEL="emb", EMBEDDING_DIM=2)


def _respond(monkeypatch: pytest.MonkeyPatch, indexes: list[int | None]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert len(json.loads(request.content)["input"]) == len(indexes)
        data = [{"embedding": [float(i or 0), 1.0], **({} if i is None else {"index": i})} for i in indexes]
        return httpx.Response(200, json={"model": "emb", "data": data})

    real = httpx.Client
    monkeypatch.setattr(ec.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_restores_input_order(monkeypatch: pytest.MonkeyPatch) -> None:
    _respond(monkeypatch, [1, 0])  # 응답 배열이 뒤집혀 옴
    assert HttpEmbeddingClient(EMB).embed(["a", "b"]) == [[0.0, 1.0], [1.0, 1.0]]


def test_single_input_without_index_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _respond(monkeypatch, [None])
    assert HttpEmbeddingClient(EMB).embed(["a"]) == [[0.0, 1.0]]


@pytest.mark.parametrize("indexes", [[0, 0], [0, None], [0, 2], [None, None], [1]])
def test_invalid_indexes_rejected(monkeypatch: pytest.MonkeyPatch, indexes: list[int | None]) -> None:
    _respond(monkeypatch, indexes)
    with pytest.raises(EmbeddingIndexInvalid):
        HttpEmbeddingClient(EMB).embed(["x"] * len(indexes))
    assert issubclass(EmbeddingIndexInvalid, RetrievalUnavailable)  # 운영 검색은 기존 실패처럼 references=[]


def test_ingest_inserts_nothing_on_bad_index(monkeypatch: pytest.MonkeyPatch) -> None:
    _respond(monkeypatch, [0, 0])
    session = MagicMock()
    chunks = [Chunk(page=1, text="본문1", tokens=1), Chunk(page=2, text="본문2", tokens=1)]
    with pytest.raises(EmbeddingIndexInvalid):
        _insert_chunks(session, HttpEmbeddingClient(EMB), {"id": "d"}, chunks)
    session.execute.assert_not_called()  # INSERT 0
