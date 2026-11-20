"""SCRUM-305 run 의 코퍼스 스냅샷 (docs/str/10 "305 실행 기록" 검색 시작 문 3 — 추가 검토 4). 실제 PostgreSQL.

태그 집계 직후 다른 세션이 청크를 넣고 커밋해도, 같은 스냅샷 세션의 다음 읽기(검색과 같은 세션)는 집계 당시 코퍼스를 본다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from tests.str import rag_eval_corpus_db as db
from tests.str import rag_eval_corpus_live as live

if TYPE_CHECKING:
    from sqlalchemy import Engine

pytestmark = pytest.mark.db
CHUNK = "f" * 64
_INSERT = text(
    "INSERT INTO ai.reference_chunks (chunk_id, doc_id, doc_title, publisher, year, page, section, lang, typologies, "
    "text, embedding, embedding_model, content_hash) VALUES (:c, 'apg-typologies-2025', 't', 'p', 2025, 1, NULL, 'en', "
    "ARRAY['CYCLE'], 'x', CAST(:v AS vector), 'm', :c)"
)


def test_counts_inside_snapshot_ignore_a_commit_from_another_session(
    monkeypatch: pytest.MonkeyPatch, _db_engine: Engine
) -> None:
    monkeypatch.setattr(db, "get_engine", lambda: _db_engine)
    with _db_engine.begin() as conn:
        conn.execute(text("DELETE FROM ai.reference_chunks WHERE chunk_id = :c"), {"c": CHUNK})
    try:
        with live._snapshot_session() as session:
            ids_before, _, total_before = live.read_tags(session)
            with _db_engine.begin() as other:  # 집계 직후 다른 세션이 적재(복원과 같은 성격)를 커밋
                other.execute(_INSERT, {"c": CHUNK, "v": "[" + ",".join(["0"] * 1536) + "]"})
            ids_after, _, total_after = live.read_tags(session)
            isolation = session.execute(text("SHOW transaction_isolation")).scalar()
            read_only = session.execute(text("SHOW transaction_read_only")).scalar()
        assert (total_after, ids_after["CYCLE"]) == (total_before, ids_before["CYCLE"])
        assert (isolation, read_only) == ("repeatable read", "on")
        assert live.read_tags()[2] == total_before + 1  # 스냅샷 밖에서는 보임
    finally:
        with _db_engine.begin() as conn:
            conn.execute(text("DELETE FROM ai.reference_chunks WHERE chunk_id = :c"), {"c": CHUNK})


def test_tags_and_locations_inside_snapshot_see_the_same_point(
    monkeypatch: pytest.MonkeyPatch, _db_engine: Engine
) -> None:
    """태그 도구 추가 검토 3 ⑮·4 ⑱ — read_tags 와 read_corpus(preflight 가 쓰는 위치·태그 전체) 사이에 다른 세션이 청크 하나를 적재·커밋해도 둘 다 적재 전."""
    monkeypatch.setattr(db, "get_engine", lambda: _db_engine)
    with _db_engine.begin() as conn:
        conn.execute(text("DELETE FROM ai.reference_chunks WHERE chunk_id = :c"), {"c": CHUNK})
    try:
        with live._snapshot_session() as session:
            ids, _, total = live.read_tags(session)
            with _db_engine.begin() as other:  # 두 읽기 사이에 커밋
                other.execute(_INSERT, {"c": CHUNK, "v": "[" + ",".join(["0"] * 1536) + "]"})
            corpus = live.read_corpus(session)
        assert CHUNK not in corpus and CHUNK not in ids["CYCLE"] and len(corpus) == total
        assert live.read_corpus()[CHUNK][2] == ("CYCLE",)  # 스냅샷 밖에서는 보임
    finally:
        with _db_engine.begin() as conn:
            conn.execute(text("DELETE FROM ai.reference_chunks WHERE chunk_id = :c"), {"c": CHUNK})
