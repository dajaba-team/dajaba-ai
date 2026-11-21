"""SCRUM-308-3 추가 검토 1 회귀 — 기대 태그·머리말(기준 커밋 manifest + 위치표) 대조 · 머리말 메타 기동 대조 · 적재 잠금."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker
from tools.ingest_corpus_ctx import ingest_ctx

from aml_ai.shared.config import Settings
from aml_ai.str.domain.constants_rag_query import REFERENCE_CTX_TABLE, REFERENCE_TABLE
from aml_ai.str.infrastructure.chunk_context_check import ctx_table_problem
from tests.str import rag_eval_v3_ctx_expect as ex
from tests.str import rag_eval_v3_ctx_live as live
from tests.str import rag_eval_v3_ctx_support as cs
from tests.str.retriever_search_support import FAN_IN_FAN_OUT_SEED, insert_chunk
from tests.str.test_chunk_context_db import DOCS, _Recording

DIM = 1536


def _docs() -> dict[str, dict]:
    """시드 태그를 쪽 단위 manifest 로 — 적재 도구와 같은 규칙(`resolve_typologies`)으로 기대 태그가 나옴."""
    out: dict[str, dict] = {}
    for row in FAN_IN_FAN_OUT_SEED:
        d = out.setdefault(row["doc_id"], {"id": row["doc_id"], **DOCS[row["doc_id"]], "typology_pages": {}})
        for t in row["typologies"]:
            d["typology_pages"].setdefault(t, []).append(row["page"])
    return out


def test_expected_tags_and_header_from_manifest() -> None:
    docs = {"d": {"id": "d", "title": "T", "publisher": "P", "year": None, "typology_pages": {"CYCLE": [2]}}}
    exp = ex.expected(
        docs, {"c1": {"doc_id": "d", "page": 2, "pos": 1}, "c2": {"doc_id": "d", "page": 3, "pos": 1}}
    )
    assert exp["c1"]["tags"] == ["CYCLE"] and exp["c2"]["tags"] == []
    assert exp["c1"]["header"] == "T — P, p.2"


def test_manifest_must_match_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ex.cg,
        "read_committed",
        lambda repo, paths: ({ex.MANIFEST: {"documents": []}}, {ex.MANIFEST: "a"}, None),
    )
    assert "manifest_sha256" in ex.read_manifest(Path("."), {"manifest_sha256": "b"})[2]
    assert ex.read_manifest(Path("."), {"manifest_sha256": "a"})[2] is None


def test_real_run_stops_before_embedding_when_ctx_differs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "r.json"
    monkeypatch.setattr(cs, "RESULT_FILE", out)
    monkeypatch.setattr(live.ex, "read_manifest", lambda repo, p: ({}, "d", None))

    @contextmanager
    def session():  # noqa: ANN202
        yield MagicMock()

    monkeypatch.setattr(live, "readonly_session", session)
    monkeypatch.setattr(live, "db_problem", lambda s, c, p: (None,))
    monkeypatch.setattr(live.rg, "embedding_model_problem", lambda s, m: None)
    monkeypatch.setattr(live, "ctx_table_problem", lambda s, m, d: None)
    monkeypatch.setattr(
        live.ex, "table_problem", lambda s, t, e: "태그 1" if t == REFERENCE_CTX_TABLE else None
    )
    monkeypatch.setattr(live.recheck, "embed_query", lambda *a: pytest.fail("임베딩까지 감"))
    loaded = {live.cg.CANDIDATES: {}}
    monkeypatch.setattr(
        live.rg, "refuse_before", lambda repo, o: ({**loaded, live.rg.POSITIONS: {"positions": {}}}, {}, None)
    )
    assert live.main([], settings=Settings(_env_file=None, AI_LLM_MOCK=False, EMBEDDING_MODEL="e")) == 2
    assert not out.exists()  # 결과 파일 0


@pytest.fixture
def factory(_db_engine: Engine):  # noqa: ANN201
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks, ai.reference_chunks_ctx"))
        ids = [insert_chunk(conn, **row) for row in FAN_IN_FAN_OUT_SEED]
        conn.execute(text("UPDATE ai.reference_chunks SET publisher = 'Pub', year = 2020"))
    f = sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)
    with f() as s:
        ingest_ctx(s, _Recording(), DOCS)
    positions = {
        c: {"doc_id": r["doc_id"], "page": r["page"], "pos": 1}
        for c, r in zip(ids, FAN_IN_FAN_OUT_SEED, strict=True)
    }
    yield f, ex.expected(_docs(), positions), ids
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks_ctx"))


@pytest.mark.db
def test_tables_match_expectation(factory) -> None:  # noqa: ANN001
    f, exp, ids = factory
    with f() as s:
        assert (
            ex.table_problem(s, REFERENCE_TABLE, exp) is None
            and ex.table_problem(s, REFERENCE_CTX_TABLE, exp) is None
        )
        got = ex.stored(s, REFERENCE_CTX_TABLE, ids[:2], "test-embed", exp)
        assert all(v[0].startswith(exp[c]["header"] + "\n") for c, v in got.items())  # 기대 머리말 + 본문


@pytest.mark.db
@pytest.mark.parametrize("change", ["drop_tag", "swap_tag", "title"])
def test_tables_differ_from_expectation(factory, change: str) -> None:  # noqa: ANN001
    f, exp, ids = factory
    fan_in = [c for c in ids if exp[c]["tags"] == ["FAN_IN"]]
    fan_out = next(c for c in ids if "FAN_OUT" in exp[c]["tags"] and "FAN_IN" not in exp[c]["tags"])
    with f() as s:
        for table in (
            "ai.reference_chunks",
            "ai.reference_chunks_ctx",
        ):  # 두 표에 같이 — 서로 대조로는 못 잡는 경우
            if change == "drop_tag":
                s.execute(
                    text(f"UPDATE {table} SET typologies = '{{}}' WHERE chunk_id = :c"), {"c": fan_in[0]}
                )  # noqa: S608
            elif change == "swap_tag":  # 개수 그대로 바꿔치기
                s.execute(
                    text(f"UPDATE {table} SET typologies = '{{FAN_OUT}}' WHERE chunk_id = :c"),
                    {"c": fan_in[0]},
                )  # noqa: S608
                s.execute(
                    text(f"UPDATE {table} SET typologies = '{{FAN_IN}}' WHERE chunk_id = :c"), {"c": fan_out}
                )  # noqa: S608
            elif table == REFERENCE_CTX_TABLE:
                s.execute(
                    text(f"UPDATE {table} SET doc_title = 'Old title' WHERE chunk_id = :c"), {"c": ids[0]}
                )  # noqa: S608
        assert ex.table_problem(s, REFERENCE_CTX_TABLE, exp) is not None
        if change == "title":  # 기동 검사도 머리말 메타를 대조(검토 1)
            assert ctx_table_problem(s, "test-embed", DIM) is not None
        s.rollback()


@pytest.mark.db
def test_stored_missing_target_fails(factory) -> None:  # noqa: ANN001
    f, exp, ids = factory
    with f() as s, pytest.raises(ValueError, match="없음"):
        ex.stored(s, REFERENCE_CTX_TABLE, [*ids[:1], "0" * 64], "test-embed", {**exp, "0" * 64: exp[ids[0]]})


@pytest.mark.db
def test_concurrent_ingest_refused_before_embedding(_db_engine: Engine) -> None:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks, ai.reference_chunks_ctx"))
        for row in FAN_IN_FAN_OUT_SEED:
            insert_chunk(conn, **row)
        conn.execute(text("UPDATE ai.reference_chunks SET publisher = 'Pub', year = 2020"))
    f = sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)
    with f() as holder, f() as second:
        holder.execute(text("LOCK TABLE ai.reference_chunks_ctx IN EXCLUSIVE MODE"))  # 첫 적재가 잡고 있음
        emb = _Recording()
        with pytest.raises(ValueError, match="다른 적재"):
            ingest_ctx(second, emb, DOCS)
        assert emb.texts == []  # 임베딩 0
        holder.rollback()
    with f() as s:
        assert s.execute(text("SELECT count(*) FROM ai.reference_chunks_ctx")).scalar() == 0
