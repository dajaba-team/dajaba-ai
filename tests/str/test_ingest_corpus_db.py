"""SCRUM-125 — tools/ingest_corpus.ingest DB 결정적 판 (`-m db`, docs/str/10).

- `ON CONFLICT (content_hash) DO NOTHING` 멱등 — 같은 manifest·같은 PDF 두 번 돌려도 행 수 같음
- `--truncate` 비우고 다시
- sha256 불일치 → 그 문서만 skip 로그 + report.skipped 에 기록
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from tests.str.ingest_corpus_support import FakeEmbedder, doc_meta, seed_pdf, write_manifest

pytestmark = pytest.mark.db


@pytest.fixture
def _ingest_session_factory(_db_engine: Engine) -> sessionmaker[Session]:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
    return sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)


def _count(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM ai.reference_chunks")).scalar() or 0


def test_idempotent_on_content_hash(
    tmp_path: Path, _ingest_session_factory: sessionmaker[Session], _db_engine: Engine
) -> None:
    from tools.ingest_corpus import ingest

    sha = seed_pdf(tmp_path, "test-doc", ["Funnel account receives multiple cash deposits."])
    manifest = write_manifest(tmp_path, [doc_meta("test-doc", sha, 1, typologies=["FAN_IN"])])

    embedder = FakeEmbedder()
    with _ingest_session_factory() as s:
        ingest(s, embedder, manifest_data=manifest, corpus_dir=tmp_path)
    n1 = _count(_db_engine)
    assert n1 >= 1

    with _ingest_session_factory() as s:
        ingest(s, embedder, manifest_data=manifest, corpus_dir=tmp_path)
    assert _count(_db_engine) == n1


def test_truncate_clears_and_reloads(
    tmp_path: Path, _ingest_session_factory: sessionmaker[Session], _db_engine: Engine
) -> None:
    from tools.ingest_corpus import ingest

    sha = seed_pdf(tmp_path, "test-doc", ["Funnel account A."])
    manifest = write_manifest(tmp_path, [doc_meta("test-doc", sha, 1, typologies=["FAN_IN"])])

    embedder = FakeEmbedder()
    with _ingest_session_factory() as s:
        ingest(s, embedder, manifest_data=manifest, corpus_dir=tmp_path)
    with _ingest_session_factory() as s:
        ingest(s, embedder, manifest_data=manifest, corpus_dir=tmp_path, truncate=True)
    assert _count(_db_engine) >= 1


def test_sha256_mismatch_skips_document(
    tmp_path: Path, _ingest_session_factory: sessionmaker[Session], _db_engine: Engine
) -> None:
    from tools.ingest_corpus import ingest

    sha_ok = seed_pdf(tmp_path, "ok-doc", ["Good content."])
    seed_pdf(tmp_path, "bad-doc", ["Bad content."])  # 실제 sha 는 쓰지 않음
    manifest = write_manifest(
        tmp_path,
        [
            doc_meta("ok-doc", sha_ok, 1, typologies=["FAN_IN"]),
            doc_meta("bad-doc", "0" * 64, 1, typologies=["FAN_IN"]),  # 틀린 해시
        ],
    )

    embedder = FakeEmbedder()
    with _ingest_session_factory() as s:
        report = ingest(s, embedder, manifest_data=manifest, corpus_dir=tmp_path)

    with _db_engine.connect() as conn:
        rows = (
            conn.execute(text("SELECT DISTINCT doc_id FROM ai.reference_chunks ORDER BY doc_id"))
            .scalars()
            .all()
        )
    assert "ok-doc" in rows
    assert "bad-doc" not in rows
    skipped_ids = [s.get("doc_id") for s in getattr(report, "skipped", [])]
    assert "bad-doc" in skipped_ids
