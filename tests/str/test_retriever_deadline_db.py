"""SCRUM-413 초안 벡터 조회 시간 제한 — 실제 PostgreSQL (docs/str/03 초안 6).

벡터 SQL 자리에 `pg_sleep` — 남은 시간(0.3초) 근처에서 끊기고 `RetrievalUnavailable`,
savepoint 라 초안 세션의 앞 쓰기는 남고 세션은 계속 쓸 수 있음. 커밋 뒤 설정은 원래 값.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.retriever_search_support import FakeEmbedder, facts_typology, vec

pytestmark = pytest.mark.db
LIMIT_S = 0.3
SLACK_S = 2.0
MARKER = "scrum413-outer-write"
_ZERO_VEC = "[" + ",".join(["0.0"] * 1536) + "]"
_INSERT_SQL = (
    "INSERT INTO ai.reference_chunks "
    "(chunk_id, doc_id, doc_title, page, typologies, text, embedding, embedding_model, content_hash) "
    "VALUES (:cid, 'outer', 'outer', 1, CAST(:ty AS text[]), 'outer', CAST(:ve AS vector), 'test', :cid)"
)


@pytest.fixture
def _factory(_db_engine: Engine) -> sessionmaker[Session]:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
    return sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)


def _sleep_on_vector_sql(s: Session):  # type: ignore[no-untyped-def]
    orig = s.execute

    def spy(stmt, *a, **kw):  # type: ignore[no-untyped-def]
        if "FROM ai.reference_chunks WHERE embedding_model" in str(stmt):
            return orig(text("SELECT pg_sleep(5)"))
        return orig(stmt, *a, **kw)

    s.execute = spy  # type: ignore[method-assign]
    return orig


def test_slow_vector_query_is_cut_and_session_keeps_outer_write(
    mixed: Facts, _factory: sessionmaker[Session]
) -> None:
    with _factory() as s:
        s.execute(text(_INSERT_SQL), {"cid": MARKER, "ty": "{FAN_IN}", "ve": _ZERO_VEC})
        s.flush()
        orig = _sleep_on_vector_sql(s)
        try:
            r = Retriever(session=s, embedder=FakeEmbedder(vec(1.0)), enabled=True)
            start = time.monotonic()
            with pytest.raises(RetrievalUnavailable):
                r.retrieve(facts_typology(mixed, Typology.FAN_IN), deadline=time.monotonic() + LIMIT_S)
            assert time.monotonic() - start < LIMIT_S + SLACK_S
        finally:
            s.execute = orig  # type: ignore[method-assign]
        count = s.execute(text("SELECT count(*) FROM ai.reference_chunks WHERE chunk_id = :c"), {"c": MARKER})
        assert count.scalar() == 1
        s.rollback()


def test_timeouts_released_after_commit(mixed: Facts, _factory: sessionmaker[Session]) -> None:
    with _factory() as s:
        r = Retriever(session=s, embedder=FakeEmbedder(vec(1.0)), enabled=True)
        assert r.retrieve(facts_typology(mixed, Typology.FAN_IN), deadline=time.monotonic() + 5.0) == []
        s.commit()
        assert s.execute(text("SHOW statement_timeout")).scalar() == "0"
        assert s.execute(text("SHOW lock_timeout")).scalar() == "0"
