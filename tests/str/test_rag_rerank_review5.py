"""SCRUM-308-2 추가 검토 5 회귀 — HTTP 200 본문 해석 실패도 응답 받음(모델 None) · 운영 허용 응답 모델 ·
재검사 대상은 유형 필터 전체(-m db) · 비유한 cosine 은 실패."""

from __future__ import annotations

import asyncio
import json
import math

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from aml_ai import main as app_main
from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.str.infrastructure.retriever_rerank import (
    LlmReranker,
    make_reranker,
    rerank_first,
    rerank_response_model_problem,
)
from tests.str import rag_eval_v3_rerank_live as live
from tests.str import rag_eval_v3_rerank_recheck as recheck
from tests.str import rag_eval_v3_rerank_report as report
from tests.str import rag_eval_v3_rerank_support as rs
from tests.str.rag_eval_v3_hybrid_support import JUDGED_TYPES
from tests.str.retriever_fill_support import ref
from tests.str.retriever_search_support import FAN_IN_FAN_OUT_SEED, insert_chunk, vec

KEYED = {"LLM_API_KEY": "k", "AI_LLM_MOCK": False}
ORDER = json.dumps({"order": ["C2", "C1"]})
REFS = [ref("a", 0.5), ref("b", 0.4)]


def _client(pick) -> HttpLlmClient:  # noqa: ANN001 — 요청 본문 → 응답 바이트
    mock = httpx.MockTransport(lambda r: httpx.Response(200, content=pick(r.content.decode())))
    return HttpLlmClient(
        Settings(_env_file=None, **KEYED), http=httpx.Client(transport=mock), async_transport=mock
    )


def _body(model: str) -> bytes:
    return json.dumps(
        {"model": model, "output_text": json.dumps({"order": ["C4", "C1", "C2", "C3"]})}
    ).encode()


@pytest.mark.parametrize("raw", [b"[]", b'{"model": "model-B", "output_te'])
def test_http200_unparseable_is_received_without_model(raw: bytes) -> None:
    reranker = LlmReranker(_client(lambda _: raw), model="model-A", allowed_model="model-A", timeout_s=8.0)
    with pytest.raises(LlmInvalidOutput) as exc:
        reranker.order_with_model("q", REFS)
    assert exc.value.response_received is True and exc.value.response_model is None


@pytest.mark.parametrize("raw", [b"[]", b'{"model": "model-A", "output_te'])
def test_one_unparseable_per_round_not_judged(raw: bytes) -> None:
    types = [JUDGED_TYPES[i % 4] for i in range(30)]
    queries = [{"id": f"Q{i:02}", "typology": t, "uses": ["hit"]} for i, t in enumerate(types)]
    cands = {
        q["id"]: [ref("w", 0.5), ref("y", 0.4), ref("z", 0.3), ref(f"{q['typology']}-a", 0.2)]
        for q in queries
    }
    texts = {q["id"]: ("emb", q["id"]) for q in queries}
    client = _client(lambda body: raw if "Q07" in body else _body("model-A"))  # 회차마다 30 중 1
    reranker = LlmReranker(client, model="model-A", allowed_model="model-A", timeout_s=8.0)
    rounds = [live.run_round(reranker, queries, cands, texts) for _ in range(rs.ROUNDS)]
    _, per_round = report.judge(queries, cands, rounds, {t: {f"{t}-a"} for t in JUDGED_TYPES})
    for rr, rnd in zip(per_round, rounds, strict=True):
        rr["response_models"] = rs.response_models(rnd)
    out = rs.final_verdict(per_round, dry=False)
    assert out["judged"] is False and out["adopt"] is False and "모델명이 없는" in out["reason"]


@pytest.mark.parametrize(("response", "reordered"), [("model-A", True), ("model-B", False), (" ", False)])
def test_operational_order_needs_allowed_response_model(response: str, reordered: bool) -> None:
    raw = json.dumps({"model": response, "output_text": ORDER}).encode()
    reranker = LlmReranker(_client(lambda _: raw), model="alias", allowed_model=" model-A ", timeout_s=8.0)
    out = rerank_first(reranker, "q", REFS, k=3, release=lambda: None)
    assert [r.chunk_id for r in out] == (["b", "a"] if reordered else ["a", "b"])


def test_empty_allowed_model_never_reorders() -> None:
    raw = json.dumps({"model": "model-A", "output_text": ORDER}).encode()
    reranker = LlmReranker(_client(lambda _: raw), model="model-A", allowed_model="", timeout_s=8.0)
    assert rerank_first(reranker, "q", REFS, k=3, release=lambda: None) == REFS


def test_make_reranker_reads_allowed_setting() -> None:
    raw = json.dumps({"model": "snap-1", "output_text": ORDER}).encode()
    s = Settings(_env_file=None, **KEYED, RAG_RERANK_MODEL="alias", RAG_RERANK_RESPONSE_MODEL="snap-1")
    out = rerank_first(make_reranker(s, _client(lambda _: raw)), "q", REFS, k=3, release=lambda: None)
    assert [r.chunk_id for r in out] == ["b", "a"]


@pytest.mark.parametrize(
    ("enabled", "value", "ok"), [(True, "", False), (True, "  ", False), (True, "m", True), (False, "", True)]
)
def test_startup_needs_allowed_model_when_enabled(enabled: bool, value: str, ok: bool) -> None:
    s = Settings(_env_file=None, RAG_RERANK_ENABLED=enabled, RAG_RERANK_RESPONSE_MODEL=value)
    assert (rerank_response_model_problem(s) is None) is ok


def test_lifespan_fails_when_enabled_without_allowed_model(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None, RAG_RERANK_ENABLED=True, RAG_RERANK_TIMEOUT_S=8)
    monkeypatch.setattr(app_main, "get_settings", lambda: s)

    async def enter() -> None:
        async with app_main.lifespan(app_main.app):
            pass

    with pytest.raises(RuntimeError, match="RAG_RERANK_RESPONSE_MODEL"):
        asyncio.run(enter())


def test_cosine_survives_overflow_and_rejects_nonfinite() -> None:
    big = [1e200] * 1536
    assert math.isclose(recheck.cosine(big, big), 1.0) and recheck.passes(recheck.cosine(big, big))
    skew = [1e200] + [0.0] * 1535
    cos = recheck.cosine(big, skew)  # 실제 ≈ 0.0255 — 순진한 계산은 NaN(이전엔 통과)
    assert math.isfinite(cos) and not recheck.passes(cos)
    assert not recheck.passes(recheck.cosine([math.nan, 1.0], [1.0, 1.0]))
    assert not recheck.passes(recheck.cosine([0.0, 0.0], [1.0, 1.0]))


def test_recheck_counts_overflow_and_nan_as_below(monkeypatch: pytest.MonkeyPatch) -> None:
    stored = {"c1": ("t1", [1e200] * 4), "c2": ("t2", [1.0, 0.0, 0.0, 0.0])}
    monkeypatch.setattr(
        recheck.HttpEmbeddingClient, "embed", lambda self, t: [[1e200, 0, 0, 0], [math.nan, 0, 0, 0]]
    )
    s = recheck.recheck(stored, Settings(_env_file=None, **KEYED, EMBEDDING_MODEL="emb"))
    assert s["below"] == 2 and "2/2" in recheck.recheck_problem(s)


def test_zero_recheck_targets_is_a_problem() -> None:
    assert "0 청크" in recheck.recheck_problem({"chunks": 0, "min_cos": None, "below": 0})


@pytest.mark.db
def test_recheck_targets_whole_typology_filter(_db_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """정답 청크가 질의에서 멀어(10위 밖이어도) 대상 — 그 청크 벡터만 다르면 중단."""
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
        ids = [insert_chunk(conn, **row) for row in FAN_IN_FAN_OUT_SEED]
        far = insert_chunk(
            conn,
            doc_id="far",
            doc_title="Far",
            page=1,
            typologies=["FAN_IN"],
            text_body="먼 정답",
            v=vec(0.0, 0.0, 1.0),
        )
        conn.execute(
            text("UPDATE ai.reference_chunks SET embedding_model = 'model-B' WHERE chunk_id = :c"),
            {"c": ids[0]},
        )
    with sessionmaker(bind=_db_engine)() as session:
        rows = recheck.filtered_rows(session, ["FAN_IN"], "test-embed")
    seeded_fan_in = {
        c for c, row in zip(ids, FAN_IN_FAN_OUT_SEED, strict=True) if "FAN_IN" in row["typologies"]
    }
    assert set(rows) == (seeded_fan_in - {ids[0]}) | {far}  # 다른 모델 행·FAN_OUT 전용 행은 빠짐
    fresh = {
        c: (vec(1.0, 0.0, 0.0) if c == far else rows[c][1]) for c in rows
    }  # 먼 청크만 다시 임베딩하면 다름
    monkeypatch.setattr(
        recheck.HttpEmbeddingClient, "embed", lambda self, t: [fresh[c] for c in sorted(rows)]
    )
    s = recheck.recheck(rows, Settings(_env_file=None, **KEYED, EMBEDDING_MODEL="test-embed"))
    assert s["chunks"] == len(rows) and s["below"] == 1 and recheck.recheck_problem(s)
