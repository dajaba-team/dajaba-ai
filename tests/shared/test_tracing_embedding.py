"""SCRUM-274 — 임베딩 호출 추적 (docs/shared/04 "추적"). 텍스트 본문·벡터는 안 남긴다.

★A ④-1: v5 `as_type="embedding"` · name `embedding` · model · 텍스트 수 · 글자 수 합 · 실패 종류.
"""

from __future__ import annotations

import pytest
from langfuse import Langfuse

from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.infrastructure.tracing import TracedEmbeddingClient
from tests.shared.tracing_support import (
    FakeTracer,
    StubEmbedding,
    _reset_tracing,  # noqa: F401 — autouse
    request_id,
)

TEXTS = ["FAN-IN 검색어 본문 하나", "second query text body"]


def _traced(tracer: FakeTracer, inner: StubEmbedding | None = None) -> TracedEmbeddingClient:
    return TracedEmbeddingClient(inner or StubEmbedding(), tracer, server_version="test-sv")


def test_one_embed_records_counts_without_text_or_vectors() -> None:
    tracer = FakeTracer()
    client = _traced(tracer)
    with request_id("rid-274-emb"):
        vectors = client.embed(TEXTS)

    assert vectors == [[0.125, 0.25, 0.5], [0.125, 0.25, 0.5]]
    assert len(tracer.observations) == 1
    obs = tracer.observations[0]
    final = obs.merged()
    assert obs.start["as_type"] == "embedding"
    assert obs.start["name"] == "embedding"
    assert obs.start["trace_context"] == {"trace_id": Langfuse.create_trace_id(seed="rid-274-emb")}
    assert final["model"] == "stub-embedding-model"
    assert final["metadata"] == {
        "request_id": "rid-274-emb",
        "server_version": "test-sv",
        "text_count": 2,
        "char_total": sum(len(t) for t in TEXTS),
    }
    recorded = repr([obs.start, *obs.updates])
    for text in TEXTS:
        assert text not in recorded
    assert "0.125" not in recorded  # 벡터 값 없음
    assert obs.ended == 1


def test_model_property_passes_through() -> None:
    assert _traced(FakeTracer()).model == "stub-embedding-model"


def test_embed_error_is_recorded_and_reraised_unchanged() -> None:
    exc = RetrievalUnavailable("embedding request failed")
    tracer = FakeTracer()
    client = _traced(tracer, StubEmbedding(exc=exc))
    with pytest.raises(RetrievalUnavailable) as excinfo:
        client.embed(TEXTS)
    assert excinfo.value is exc
    final = tracer.observations[0].merged()
    assert final["level"] == "ERROR"
    assert final["status_message"] == "RetrievalUnavailable"
    assert tracer.observations[0].ended == 1


@pytest.mark.parametrize("where", ["start", "update", "end"])
def test_tracer_errors_do_not_change_vectors(where: str) -> None:
    client = _traced(FakeTracer(**{f"raise_on_{where}": RuntimeError("tracer down")}))
    assert client.embed(TEXTS) == [[0.125, 0.25, 0.5], [0.125, 0.25, 0.5]]
