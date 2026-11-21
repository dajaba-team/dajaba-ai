"""SCRUM-308-3 청크 맥락 — 새 표 모양 · 적재(복사·거절·INSERT 0) · 기동 대조 · 새 표 검색 · 비유한 거절 (-m db)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from tools.ingest_corpus_ctx import ingest_ctx

from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain.constants_rag_query import REFERENCE_CTX_TABLE
from aml_ai.str.infrastructure.chunk_context_check import ctx_table_problem
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.retriever_search_support import (
    FAN_IN_FAN_OUT_SEED,
    FakeEmbedder,
    facts_typology,
    insert_chunk,
    vec,
)

pytestmark = pytest.mark.db

DIM = 1536
DOCS = {
    row["doc_id"]: {"title": row["doc_title"], "publisher": "Pub", "year": 2020}
    for row in FAN_IN_FAN_OUT_SEED
}


class _Recording:
    model = "test-embed"

    def __init__(self, v: list[float] | None = None, fail: bool = False) -> None:
        self.texts: list[str] = []
        self._v, self._fail = v or vec(0.0, 1.0), fail

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._fail:
            raise RetrievalUnavailable("down")
        self.texts.extend(texts)
        return [self._v for _ in texts]


@pytest.fixture
def factory(_db_engine: Engine) -> Iterator[sessionmaker[Session]]:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks, ai.reference_chunks_ctx"))
        for row in FAN_IN_FAN_OUT_SEED:
            insert_chunk(conn, **row)
        conn.execute(text("UPDATE ai.reference_chunks SET publisher = 'Pub', year = 2020"))
    yield sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks_ctx"))


def _rows(s: Session, table: str) -> list:
    return s.execute(
        text(
            f"SELECT chunk_id, doc_id, page, typologies, text, content_hash, embedding::text AS v FROM {table} ORDER BY chunk_id"
        )
    ).all()  # noqa: S608


def test_ctx_table_same_columns_and_indexes(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        cols = {t: s.execute(text("SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                                  "WHERE table_schema='ai' AND table_name=:t ORDER BY ordinal_position"), {"t": t}).all()
                for t in ("reference_chunks", "reference_chunks_ctx")}  # fmt: skip
        idx = (
            s.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname='ai' AND tablename='reference_chunks_ctx'"
                )
            )
            .scalars()
            .all()
        )
    assert cols["reference_chunks"] == cols["reference_chunks_ctx"]
    assert any("hnsw (embedding vector_cosine_ops)" in d for d in idx) and any(
        "gin (typologies)" in d for d in idx
    )
    assert sum("UNIQUE" in d for d in idx) == 2  # PK chunk_id · content_hash


def test_ingest_copies_rows_and_embeds_header(factory: sessionmaker[Session]) -> None:
    emb = _Recording()
    with factory() as s:
        before = _rows(s, "ai.reference_chunks")
        assert ingest_ctx(s, emb, DOCS) == len(FAN_IN_FAN_OUT_SEED)
    with factory() as s:
        cur, ctx = _rows(s, "ai.reference_chunks"), _rows(s, REFERENCE_CTX_TABLE)
        assert cur == before  # 지금 표 변경 0
        assert [r[:6] for r in ctx] == [r[:6] for r in cur]  # chunk_id·문서·쪽·태그·본문·해시 그대로
        assert all(
            t.split("\n", 1)[0].endswith(f"— Pub, 2020, p.{r.page}")
            for t, r in zip(emb.texts, cur, strict=True)
        )
        assert [t.split("\n", 1)[1] for t in emb.texts] == [r.text for r in cur]  # 저장 text 는 머리말 없음
        assert ctx_table_problem(s, "test-embed", DIM) is None


@pytest.mark.parametrize("case", ["not_empty", "meta", "model", "embed_fail"])
def test_ingest_refuses_and_inserts_nothing(factory: sessionmaker[Session], case: str) -> None:
    with factory() as s:
        if case == "not_empty":
            ingest_ctx(s, _Recording(), DOCS)
        docs = {k: {**v, "year": 1999} for k, v in DOCS.items()} if case == "meta" else DOCS
        if case == "model":
            s.execute(text("UPDATE ai.reference_chunks SET embedding_model = 'other' WHERE page = 1"))
            s.commit()
        before = s.execute(text("SELECT count(*) FROM ai.reference_chunks_ctx")).scalar()
        with pytest.raises((ValueError, RetrievalUnavailable)):
            ingest_ctx(s, _Recording(fail=case == "embed_fail"), docs)
    with factory() as s:
        assert s.execute(text("SELECT count(*) FROM ai.reference_chunks_ctx")).scalar() == before


@pytest.mark.parametrize("change", ["delete", "tag", "text", "model"])
def test_ctx_table_problem_detects_difference(factory: sessionmaker[Session], change: str) -> None:
    with factory() as s:
        ingest_ctx(s, _Recording(), DOCS)
        target = s.execute(
            text("SELECT chunk_id FROM ai.reference_chunks_ctx ORDER BY chunk_id LIMIT 1")
        ).scalar()
        sql = {"delete": "DELETE FROM ai.reference_chunks_ctx WHERE chunk_id = :c",
               "tag": "UPDATE ai.reference_chunks_ctx SET typologies = '{CYCLE}' WHERE chunk_id = :c",
               "text": "UPDATE ai.reference_chunks_ctx SET text = text || ' ' WHERE chunk_id = :c",
               "model": "UPDATE ai.reference_chunks_ctx SET embedding_model = 'other' WHERE chunk_id = :c"}[change]  # fmt: skip
        s.execute(text(sql), {"c": target})
        assert ctx_table_problem(s, "test-embed", DIM) is not None
        s.rollback()


def test_empty_ctx_table_is_a_problem(factory: sessionmaker[Session]) -> None:
    with factory() as s:
        assert "행 수 0" in ctx_table_problem(s, "test-embed", DIM)


def test_retriever_reads_ctx_table(factory: sessionmaker[Session], mixed: Facts) -> None:
    with factory() as s:
        ingest_ctx(s, _Recording(vec(0.0, 1.0)), DOCS)  # 새 표는 전부 같은 벡터
    with factory() as s:
        f = facts_typology(mixed, Typology.FAN_IN)
        cur = Retriever(s, FakeEmbedder(vec(1.0)), enabled=True).retrieve(f)
        ctx = Retriever(s, FakeEmbedder(vec(1.0)), enabled=True, table=REFERENCE_CTX_TABLE).retrieve(f)
    assert len(cur) == len(ctx) == 3 and {r.chunk_id for r in cur} == {r.chunk_id for r in ctx}
    assert all(abs(r.score) < 1e-6 for r in ctx) and all(
        r.score > 0.5 for r in cur
    )  # 새 표 cosine 은 새 벡터 기준
    assert [r.chunk_id for r in ctx] == sorted(r.chunk_id for r in ctx)  # 전부 동점 → chunk_id 순


@pytest.mark.parametrize("bad", ["NaN", "Infinity"])
def test_pgvector_rejects_nonfinite(factory: sessionmaker[Session], bad: str) -> None:
    literal = "[" + ",".join([bad] + ["0"] * (DIM - 1)) + "]"
    with factory() as s, pytest.raises(DBAPIError):
        s.execute(text("SELECT CAST(:v AS vector)"), {"v": literal})
