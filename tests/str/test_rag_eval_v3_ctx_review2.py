"""SCRUM-308-3 추가 검토 2 회귀 — 본문 해시 재계산 · 두 표 722 전체 재임베딩 대조 · RAG 전체 끔이면 기동 대조 안 함."""

from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from sqlalchemy import text

from aml_ai.shared import chunk_context_state, versioning
from aml_ai.shared.config import Settings
from aml_ai.str.domain.constants_rag_query import REFERENCE_CTX_TABLE, REFERENCE_TABLE
from aml_ai.str.infrastructure import chunk_context_check as check
from tests.str import rag_eval_v3_ctx_expect as ex
from tests.str import rag_eval_v3_ctx_live as live
from tests.str import rag_eval_v3_rerank_recheck as recheck
from tests.str.rag_eval_v3_hybrid_support import QUERIES_FILE
from tests.str.retriever_fill_support import ref
from tests.str.test_rag_eval_v3_ctx_review1 import factory  # noqa: F401 — 적재된 두 표 + 기대 매핑
from tests.str.test_rag_eval_v3_rerank_review2 import _loaded

KEYED = {"LLM_API_KEY": "k", "AI_LLM_MOCK": False, "EMBEDDING_MODEL": "emb"}


@pytest.mark.db
@pytest.mark.parametrize(
    "tables", [("ai.reference_chunks", "ai.reference_chunks_ctx"), ("ai.reference_chunks_ctx",)]
)
def test_changed_body_is_refused(factory, tables: tuple[str, ...]) -> None:  # noqa: ANN001, F811
    """chunk_id·content_hash 는 그대로 두고 본문만 바꿈 — 두 표 같이 바꿔도(서로 대조로는 못 잡음) 거절."""
    f, exp, ids = factory
    with f() as s:
        assert (
            ex.table_problem(s, REFERENCE_TABLE, exp) is None
            and ex.table_problem(s, REFERENCE_CTX_TABLE, exp) is None
        )
        for table in tables:
            s.execute(text(f"UPDATE {table} SET text = 'changed body' WHERE chunk_id = :c"), {"c": ids[0]})  # noqa: S608
        assert "본문 해시 1" in ex.table_problem(s, REFERENCE_CTX_TABLE, exp)
        s.rollback()


@pytest.mark.db
def test_recheck_targets_every_chunk(factory) -> None:  # noqa: ANN001, F811
    f, exp, ids = factory
    with f() as s:
        got = ex.stored(s, REFERENCE_CTX_TABLE, sorted(exp), "test-embed", exp)
    assert set(got) == set(ids)  # 유형 필터와 무관하게 전부


def _same(stored: dict) -> dict:
    return {t: v for t, v in stored.values()}  # 문장 → 저장 벡터 = "다시 임베딩해도 같음"


def test_full_recheck_catches_vector_outside_old_65(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = {f"c{i}": (f"body{i}", [1.0, float(i)]) for i in range(5)}
    ctx = {c: (f"H\n{t}", [float(i), 1.0]) for i, (c, (t, _)) in enumerate(cur.items())}
    truth = {**_same(cur), **_same(ctx)}
    monkeypatch.setattr(recheck.HttpEmbeddingClient, "embed", lambda self, texts: [truth[t] for t in texts])
    s = Settings(_env_file=None, **KEYED)
    assert recheck.recheck_problem(recheck.recheck(ctx, s)) is None
    broken = {**ctx, "c4": (ctx["c4"][0], cur["c4"][1])}  # 머리말 없는 지금 표 벡터로 되돌림
    out = recheck.recheck(broken, s)
    assert out["below"] == 1 and recheck.recheck_problem(out)


def test_external_calls_are_queries_plus_both_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded = _loaded()
    queries = loaded["tests/str/rag_eval_v3/queries_dev.json"]["queries"]
    stored = {"current": {f"c{i}": (f"b{i}", [1.0, 0.0]) for i in range(722)}}
    stored["ctx"] = {c: (f"H\n{t}", v) for c, (t, v) in stored["current"].items()}
    tops = {q["id"]: ([ref(f"{q['typology']}-a", 0.5)] if q["typology"] else []) for q in queries}
    got = {
        **{k: tops for k in ("current_on", "ctx_on", "current_off", "ctx_off")},
        "stored": stored,
        "ctx_table": "x",
    }
    calls = {"query": 0, "recheck": 0}
    monkeypatch.setattr(
        live.recheck, "embed_query", lambda t, s, d: calls.__setitem__("query", calls["query"] + 1)
    )
    monkeypatch.setattr(live, "fetch", lambda qs, p, ld, s, dry: got)
    monkeypatch.setattr(
        recheck.HttpEmbeddingClient,
        "embed",
        lambda self, texts: (
            calls.__setitem__("recheck", calls["recheck"] + len(texts)) or [[1.0, 0.0]] * len(texts)
        ),
    )
    doc = live.evaluate(Settings(_env_file=None, **KEYED), loaded, {}, dry=False)
    assert calls == {"query": sum(1 for q in queries if q["typology"]), "recheck": 722 + 722}
    assert doc["configuration"]["recheck_chunks"] == {"current": 722, "ctx": 722}
    assert len(doc["configuration"]["vector_sha256"]["ctx"]) == 64
    real = json.loads(QUERIES_FILE.read_text(encoding="utf-8"))["queries"]
    assert sum(1 for q in real if q["typology"]) == 32  # 실측: 질의 32 + 722 + 722


def test_rag_off_skips_startup_check() -> None:
    s = Settings(
        _env_file=None, RAG_ENABLED=False, RAG_CHUNK_CONTEXT_ENABLED=True, NARRATIVE_PROMPT="narrative_v4"
    )
    opened: list = []

    @contextmanager
    def open_session():  # noqa: ANN202
        opened.append(1)
        yield None

    assert s.rag_chunk_context_active is False
    check.verify_on_startup(s, open_session)
    assert opened == [] and chunk_context_state.in_use(s) is False
    assert versioning.retrieval_version(s) is None  # RAG 끔 — 버전 자체가 없음(꼬리도 없음)
