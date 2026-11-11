"""SCRUM-125 — HNSW 사후 필터 누락 재현·relaxed+resort 해결 검증 (docs/str/10 "인덱스", -m db).

기본 플래너는 좁은 유형에 GIN(typologies) 를 먼저 — HNSW 안 탐. 사후 필터 누락은
`enable_seqscan=off` + `enable_bitmapscan=off` 로 HNSW 강제한 세션에서만 재현 (09 2026-11-11).
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.retriever_search_support import (
    FakeEmbedder,
    facts_typology,
    seed_ef_search_boundary,
    vec,
)

pytestmark = pytest.mark.db


@pytest.fixture
def _retriever_session_factory(_db_engine: Engine) -> sessionmaker[Session]:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
    return sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)


def test_rare_typology_beyond_default_ef_search_still_returned(
    _db_engine: Engine, mixed: Facts, _retriever_session_factory: sessionmaker[Session]
) -> None:
    """HNSW 강제 세션에서 iterative_scan=off → 0건 (사후 필터 누락 재현), Retriever(relaxed+resort) → 1건.

    FAN_IN 60개(쿼리에 가까움, 상위 ef_search 안) + FAN_OUT 1개(멀리, ef_search 밖).
    EXPLAIN 에 `ix_reference_chunks_embedding` (HNSW) 찍히는지 함께 확인.
    """
    sql = (
        "SELECT doc_id FROM ai.reference_chunks WHERE typologies @> ARRAY['FAN_OUT']::text[] "
        "ORDER BY embedding <=> CAST(:v AS vector) LIMIT 3"
    )
    qvec = "[" + ",".join(["1.0"] + ["0.0"] * 1535) + "]"

    with _db_engine.begin() as conn:
        seed_ef_search_boundary(conn)

    # (1) iterative_scan off + HNSW 강제 + ef_search=10 → 0건 (noise 150 이 ef_search 밖으로 FAN_OUT 밀어냄)
    with _retriever_session_factory() as s:
        s.execute(text("SET LOCAL enable_seqscan = off"))
        s.execute(text("SET LOCAL enable_bitmapscan = off"))
        s.execute(text("SET LOCAL hnsw.ef_search = 10"))
        plan = [p[0] for p in s.execute(text("EXPLAIN " + sql), {"v": qvec}).all()]
        assert any("ix_reference_chunks_embedding" in p for p in plan), f"HNSW 미사용: {plan}"
        rows = s.execute(text(sql), {"v": qvec}).all()
        assert rows == [], f"iterative_scan off 에서 FAN_OUT 나옴 — 재현 실패: {rows}"

    # (2) Retriever (내부 SET LOCAL relaxed+resort) + HNSW 강제 + ef_search=10 → 1건
    with _retriever_session_factory() as s:
        s.execute(text("SET LOCAL enable_seqscan = off"))
        s.execute(text("SET LOCAL enable_bitmapscan = off"))
        s.execute(text("SET LOCAL hnsw.ef_search = 10"))
        retriever = Retriever(session=s, embedder=FakeEmbedder(vec(1.0)), enabled=True)
        result = retriever.retrieve(facts_typology(mixed, Typology.FAN_OUT))
    assert len(result) == 1, "relaxed+resort 로도 FAN_OUT 안 나옴 — 미해결"
    assert result[0].doc_id == "rare-fanout"
