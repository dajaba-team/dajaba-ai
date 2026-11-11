"""SCRUM-125 — Retriever._search 가 savepoint(begin_nested) 로 outer 트랜잭션 쓰기 보존 (-m db).

draft_service._references 와 self.generations.claim 이 같은 session 을 공유 — _search 가
session.rollback 하면 claim 쓰기까지 날아감. begin_nested 로 바뀌면 유지.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.retriever_search_support import FakeEmbedder, facts_typology, vec

pytestmark = pytest.mark.db

MARKER = "outer-write-marker-12345"
_ZERO_VEC = "[" + ",".join(["0.0"] * 1536) + "]"
_INSERT_SQL = (
    "INSERT INTO ai.reference_chunks "
    "(chunk_id, doc_id, doc_title, page, typologies, text, embedding, embedding_model, content_hash) "
    "VALUES (:cid, 'outer', 'outer', 1, CAST(:ty AS text[]), 'outer', CAST(:ve AS vector), 'test', :cid)"
)


@pytest.fixture
def _retriever_session_factory(_db_engine: Engine) -> sessionmaker[Session]:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
    return sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)


def _patch_select_failure(s: Session) -> tuple:  # type: ignore[type-arg]
    """SELECT (FROM ai.reference_chunks WHERE typologies) 에만 OperationalError 유도."""
    orig = s.execute

    def spy(stmt, *a, **kw):  # type: ignore[no-untyped-def]
        if "FROM ai.reference_chunks WHERE typologies" in str(stmt):
            raise OperationalError("induced", {}, Exception("induced"))
        return orig(stmt, *a, **kw)

    s.execute = spy  # type: ignore[method-assign]
    return s, orig


def test_search_failure_preserves_outer_writes(
    mixed: Facts, _retriever_session_factory: sessionmaker[Session]
) -> None:
    """outer INSERT → _search SELECT 실패 → savepoint 만 rollback, outer INSERT 유지."""
    with _retriever_session_factory() as s:
        s.execute(text(_INSERT_SQL), {"cid": MARKER, "ty": "{FAN_IN}", "ve": _ZERO_VEC})
        s.flush()
        _, orig = _patch_select_failure(s)
        try:
            retriever = Retriever(session=s, embedder=FakeEmbedder(vec(1.0)), enabled=True)
            with pytest.raises(RetrievalUnavailable):
                retriever.retrieve(facts_typology(mixed, Typology.FAN_IN))
        finally:
            s.execute = orig  # type: ignore[method-assign]
        count = s.execute(
            text("SELECT count(*) FROM ai.reference_chunks WHERE chunk_id = :cid"),
            {"cid": MARKER},
        ).scalar()
        assert count == 1, "outer INSERT 가 날아감 — session.rollback 사용 중"
        s.rollback()
