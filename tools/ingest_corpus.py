"""PDF → 쪽별 청크 → 임베딩 → 참고 사례 적재 (docs/str/10).

--verify: sha256·쪽수 확인만. --truncate: 비우고 다시 적재.
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import TypedDict

import pymupdf
from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.config import get_settings
from aml_ai.shared.db import get_engine
from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient, make_embedding_client
from aml_ai.shared.logging import setup_logging
from aml_ai.str.domain.constants import CHUNK_OVERLAP_TOKENS, CHUNK_TOKENS, EMBED_BATCH
from tools.corpus_chunks import (
    Chunk,
    chunk_pdf_pages,
    compute_content_hash,
    estimate_tokens,
    resolve_typologies,
)

__all__ = [
    "Chunk",
    "IngestReport",
    "chunk_pdf_pages",
    "compute_content_hash",
    "estimate_tokens",
    "resolve_typologies",
    "ingest",
]

log = logging.getLogger(__name__)
_INSERT = text(
    "INSERT INTO ai.reference_chunks "
    "(chunk_id, doc_id, doc_title, publisher, year, page, section, lang, "
    "typologies, text, embedding, embedding_model, content_hash) "
    "VALUES (:chunk_id, :doc_id, :doc_title, :publisher, :year, :page, :section, :lang, "
    "CAST(:typologies AS text[]), :text, CAST(:embedding AS vector), :embedding_model, :content_hash) "
    "ON CONFLICT (content_hash) DO NOTHING"
)


class SkippedDocument(TypedDict):
    doc_id: str
    reason: str


@dataclass
class IngestReport:
    docs_loaded: int = 0
    chunks_total: int = 0
    skipped: list[SkippedDocument] = field(default_factory=list)


def _read_pages(meta: dict, corpus_dir: Path) -> tuple[list[str], str | None]:
    pdf_path = corpus_dir / "pdf" / f"{meta['id']}.pdf"
    try:
        digest = sha256(pdf_path.read_bytes()).hexdigest()
    except OSError:
        return [], "pdf_unreadable"
    if digest != meta.get("sha256"):
        return [], "sha256_mismatch"
    try:
        with pymupdf.open(pdf_path) as document:
            if meta.get("pages") is not None and len(document) != meta["pages"]:
                return [], "page_count_mismatch"
            return [page.get_text() for page in document], None
    except (OSError, RuntimeError, ValueError):
        return [], "pdf_invalid"


def _chunk_row(meta: dict, chunk: Chunk, vector: list[float], model: str) -> dict[str, object]:
    content_hash = compute_content_hash(meta["id"], chunk.page, chunk.text)
    return {
        "chunk_id": content_hash,
        "content_hash": content_hash,
        "doc_id": meta["id"],
        "doc_title": meta["title"],
        "publisher": meta.get("publisher"),
        "year": meta.get("year"),
        "page": chunk.page,
        "section": None,
        "lang": meta.get("lang"),
        "typologies": resolve_typologies(meta, chunk.page),
        "text": chunk.text,
        "embedding": str(vector),
        "embedding_model": model,
    }


def _insert_chunks(session: Session, embedder: EmbeddingClient, meta: dict, chunks: list[Chunk]) -> None:
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        vectors = embedder.embed([chunk.text for chunk in batch])
        if len(vectors) != len(batch):
            raise RetrievalUnavailable("embedding count mismatch")
        rows = [
            _chunk_row(meta, chunk, vector, getattr(embedder, "model", ""))
            for chunk, vector in zip(batch, vectors, strict=True)
        ]
        session.execute(_INSERT, rows)


def ingest(
    session: Session,
    embedder: EmbeddingClient,
    *,
    manifest_data: dict,
    corpus_dir: Path,
    truncate: bool = False,
    verify_only: bool = False,
) -> IngestReport:
    report = IngestReport()
    try:
        if truncate and not verify_only:
            session.execute(text("TRUNCATE ai.reference_chunks"))
        for meta in manifest_data["documents"]:
            pages, reason = _read_pages(meta, corpus_dir)
            if reason:
                report.skipped.append({"doc_id": meta["id"], "reason": reason})
                log.warning("corpus_document_skipped", extra={"doc_id": meta["id"], "skipped": 1})
                continue
            chunks = [] if verify_only else chunk_pdf_pages(pages, CHUNK_TOKENS, CHUNK_OVERLAP_TOKENS)
            if not verify_only:
                _insert_chunks(session, embedder, meta, chunks)
            report.docs_loaded += 1
            report.chunks_total += len(chunks)
            log.info("corpus_document_loaded", extra={"doc_id": meta["id"], "chunks": len(chunks)})
        if not verify_only:
            session.commit()
    except Exception:
        session.rollback()
        raise
    log.info("corpus_ingest_finished", extra={"chunks": report.chunks_total, "skipped": len(report.skipped)})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    setup_logging(settings)
    manifest_data = json.loads((settings.corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    with Session(get_engine()) as session:
        ingest(
            session,
            make_embedding_client(settings),
            manifest_data=manifest_data,
            corpus_dir=settings.corpus_dir,
            truncate=args.truncate,
            verify_only=args.verify,
        )


if __name__ == "__main__":
    main()
