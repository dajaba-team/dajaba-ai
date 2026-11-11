"""SCRUM-125 — migrations/versions/0004_reference_chunks (docs/shared/03, INTENT 새 파일).

- upgrade → `ai.reference_chunks` 칸·`content_hash UNIQUE`·HNSW(cosine)·GIN(typologies)
- `embedding vector(1536)` 고정 — Alembic 이 Settings import 안 함 (환경변수가 결과 바꾸는 것 방지, INTENT ★A 2)
- downgrade → 테이블 사라짐
- 확장 없으면 RuntimeError ("pgvector 확장 없음 — shared/03 절차") — 조용히 넘어가지 않음

develop 에서 실패: 파일 자체가 없음. `_db_engine` 이 alembic upgrade head 를 돌릴 때 `0003` 에서 멈춤.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text

pytestmark = pytest.mark.db


def test_upgrade_creates_reference_chunks(_db_engine: Engine) -> None:
    """ai.reference_chunks 테이블·칸 존재 — alembic upgrade head 가 돈 상태."""
    with _db_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, data_type, udt_name, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema='ai' AND table_name='reference_chunks' "
                "ORDER BY ordinal_position"
            )
        ).all()
    cols = {r[0]: {"data_type": r[1], "udt": r[2], "null": r[3]} for r in rows}
    required = {
        "chunk_id",
        "doc_id",
        "doc_title",
        "page",
        "typologies",
        "text",
        "embedding",
        "embedding_model",
        "content_hash",
        "created_at",
    }
    assert required.issubset(cols.keys()), f"누락 칸: {required - cols.keys()}"
    assert cols["typologies"]["data_type"] == "ARRAY"
    assert cols["embedding"]["udt"] == "vector"
    assert cols["chunk_id"]["null"] == "NO"


def test_embedding_vector_dim_is_1536(_db_engine: Engine) -> None:
    """vector(1536) 고정 — INTENT ★A 2. pg_attribute.atttypmod 로 차원 확인."""
    with _db_engine.connect() as conn:
        atttypmod = conn.execute(
            text(
                "SELECT a.atttypmod "
                "FROM pg_attribute a "
                "JOIN pg_class c ON a.attrelid = c.oid "
                "JOIN pg_namespace n ON c.relnamespace = n.oid "
                "WHERE n.nspname='ai' AND c.relname='reference_chunks' AND a.attname='embedding'"
            )
        ).scalar()
    # pgvector 는 atttypmod 에 차원을 그대로 저장 (음수가 아닌 raw dim)
    assert atttypmod == 1536


def test_content_hash_is_unique(_db_engine: Engine) -> None:
    """content_hash UNIQUE — 멱등 적재의 뼈대 (INTENT 바꿀 파일 tools/ingest_corpus.py)."""
    with _db_engine.connect() as conn:
        count = conn.execute(
            text(
                "SELECT count(*) FROM pg_indexes "
                "WHERE schemaname='ai' AND tablename='reference_chunks' "
                "AND indexdef ILIKE '%UNIQUE%content_hash%'"
            )
        ).scalar()
    assert count and count >= 1, "content_hash UNIQUE 인덱스 없음"


def test_hnsw_index_on_embedding_cosine(_db_engine: Engine) -> None:
    """HNSW(embedding vector_cosine_ops) — 거리 연산자 <=>, INTENT _search 와 맞춤."""
    with _db_engine.connect() as conn:
        rows = (
            conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE schemaname='ai' AND tablename='reference_chunks'")
            )
            .scalars()
            .all()
        )
    hnsw_defs = [d for d in rows if "using hnsw" in d.lower()]
    assert hnsw_defs, "HNSW 인덱스 없음"
    assert any("vector_cosine_ops" in d for d in hnsw_defs), f"HNSW cosine ops 지정 필요: {hnsw_defs}"


def test_gin_index_on_typologies(_db_engine: Engine) -> None:
    """GIN(typologies) — 유형 필터 `typologies @> ARRAY[:t]` 인덱스 스캔용."""
    with _db_engine.connect() as conn:
        rows = (
            conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE schemaname='ai' AND tablename='reference_chunks'")
            )
            .scalars()
            .all()
        )
    gin_defs = [d for d in rows if "using gin" in d.lower() and "typologies" in d.lower()]
    assert gin_defs, "GIN(typologies) 인덱스 없음"


def test_downgrade_drops_table(_db_engine: Engine) -> None:
    """upgrade head 뒤 테이블 존재 → downgrade -1 → 사라짐 → upgrade head 복구.

    develop 에서는 0004 가 없어 upgrade head 가 0003 에서 멈춤 → 첫 번째 assert 에서 fail
    (trivially pass 를 막기 위해 '먼저 존재' 확인).
    """
    from alembic import command
    from alembic.config import Config

    from tests.str.conftest import REPO_ROOT

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", str(_db_engine.url))

    with _db_engine.connect() as conn:
        exists_before = conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='ai' AND table_name='reference_chunks'"
            )
        ).scalar()
    assert exists_before, "upgrade head 뒤에도 ai.reference_chunks 없음 — 0004 가 반영 안 됨"

    try:
        command.downgrade(cfg, "-1")  # 0004 → 0003
        with _db_engine.connect() as conn:
            exists_after = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema='ai' AND table_name='reference_chunks'"
                )
            ).scalar()
        assert exists_after is None, "downgrade 뒤에도 테이블이 남아 있음"
    finally:
        command.upgrade(cfg, "head")  # 다른 테스트를 위해 복구
