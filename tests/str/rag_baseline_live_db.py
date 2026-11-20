"""SCRUM-146 기준선의 읽기 전용 DB 조회와 PDF 쪽 안 순번 복원."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict

from sqlalchemy import text
from sqlalchemy.orm import Session
from tools.corpus_chunks import chunk_pdf_pages, compute_content_hash

from aml_ai.shared.db import get_engine
from aml_ai.str.domain.constants import CHUNK_OVERLAP_TOKENS, CHUNK_TOKENS, RAG_CANDIDATES
from tests.str.rag_baseline_support import page_seq


class ChunkRow(TypedDict):
    chunk_id: str
    doc_id: str
    page: int
    lang: str | None


class RankedChunk(ChunkRow):
    cosine: float


@contextmanager
def readonly_session() -> Iterator[Session]:
    with Session(get_engine()) as session, session.begin():
        session.execute(text("SET TRANSACTION READ ONLY"))
        yield session


def corpus_rows(session: Session) -> dict[str, ChunkRow]:
    rows = session.execute(
        text("SELECT chunk_id, doc_id, page, lang FROM ai.reference_chunks ORDER BY chunk_id")
    ).mappings()
    return {r["chunk_id"]: ChunkRow(**r) for r in rows}


def language_chars(session: Session) -> dict[str, int]:
    return {
        row.lang: int(row.characters)
        for row in session.execute(
            text(
                "SELECT lang, sum(char_length(text)) AS characters "
                "FROM ai.reference_chunks GROUP BY lang ORDER BY lang"
            )
        )
    }


def full_ranking(session: Session, vector: list[float]) -> list[RankedChunk]:
    # d + 0 forces an exact full sort, without an approximate HNSW index scan.
    rows = session.execute(
        text(
            "SELECT chunk_id, doc_id, page, lang, "
            "1 - (embedding <=> CAST(:vec AS vector)) AS cosine "
            "FROM ai.reference_chunks "
            "ORDER BY (embedding <=> CAST(:vec AS vector)) + 0, chunk_id"
        ),
        {"vec": str(vector)},
    ).mappings()
    return [RankedChunk(**r) for r in rows]


def explain(session: Session, vector: list[float], typology: str) -> list[str]:
    session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    return list(
        session.execute(
            text(
                "EXPLAIN WITH r AS MATERIALIZED ("
                "SELECT chunk_id, doc_id, doc_title, page, text, "
                "embedding <=> CAST(:vec AS vector) AS d "
                "FROM ai.reference_chunks WHERE typologies @> ARRAY[:ty]::text[] "
                "ORDER BY embedding <=> CAST(:vec AS vector) LIMIT :cand) "
                "SELECT chunk_id, doc_id, doc_title, page, text, 1 - d AS score "
                "FROM r ORDER BY d + 0 LIMIT :k"
            ),
            {"vec": str(vector), "ty": typology, "cand": RAG_CANDIDATES, "k": RAG_CANDIDATES},
        ).scalars()
    )


def restore_sequences(manifest: dict, corpus_dir: Path) -> tuple[dict[str, int], dict[str, str]]:
    from tools.ingest_corpus import _read_pages  # pymupdf(corpus extra) — 쪽 복원 때만(SCRUM-305 추가 검토 2)

    order: list[tuple[str, int, str]] = []
    unavailable: dict[str, str] = {}
    for meta in manifest["documents"]:
        pages, reason = _read_pages(meta, corpus_dir)
        if reason:
            unavailable[meta["id"]] = reason
            continue
        order.extend(
            (meta["id"], chunk.page, compute_content_hash(meta["id"], chunk.page, chunk.text))
            for chunk in chunk_pdf_pages(pages, CHUNK_TOKENS, CHUNK_OVERLAP_TOKENS)
        )
    return page_seq(order), unavailable
