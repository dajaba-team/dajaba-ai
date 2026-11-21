"""청크 맥락 새 표 적재 (SCRUM-308-3, docs/str/10 "청크 맥락") — 진희 터미널에서 한 번.

지금 표 `ai.reference_chunks` 를 **읽기만** 해 `chunk_id`·문서·쪽·태그·본문을 그대로 복사하고, 임베딩만
머리말(`{title} — {publisher}, {year}, p.{page}`) + 본문으로 다시 만든다(공통 클라이언트 — 응답 model·index 검사).
거절: 새 표 잠금을 못 잡음(다른 적재 중 — 임베딩 전) · 새 표가 비어 있지 않음 · 지금 표 비어 있음 · 지금 표 메타(제목·발행처·연도) ≠ manifest · 지금 표
`embedding_model` 이 설정 모델 하나가 아님. 한 트랜잭션 — 실패면 INSERT 0. 지금 표·ES·manifest 변경 0. 로그는 개수만.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from aml_ai.shared.config import get_settings
from aml_ai.shared.db import get_engine
from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient, make_embedding_client
from aml_ai.shared.logging import setup_logging
from aml_ai.str.domain.chunk_context import context_header, context_text

log = logging.getLogger(__name__)

_COLUMNS = "chunk_id, doc_id, doc_title, publisher, year, page, section, lang, typologies, text, content_hash"
_READ = text(f"SELECT {_COLUMNS} FROM ai.reference_chunks ORDER BY chunk_id")
_INSERT = text(
    f"INSERT INTO ai.reference_chunks_ctx ({_COLUMNS}, embedding, embedding_model) "
    "VALUES (:chunk_id, :doc_id, :doc_title, :publisher, :year, :page, :section, :lang, :typologies, :text, "
    ":content_hash, CAST(:embedding AS vector), :embedding_model)"
)


def _lock(session: Session) -> None:
    """빈 표 검사 **전에** 새 표 쓰기 잠금 — 커밋까지 유지. 못 잡으면 임베딩 전에 거절(추가 검토 1 — 동시 적재)."""
    try:
        session.execute(text("LOCK TABLE ai.reference_chunks_ctx IN EXCLUSIVE MODE NOWAIT"))
    except OperationalError:
        raise ValueError("다른 적재가 새 표를 잡고 있음 — 임베딩 전에 멈춤") from None


def refuse_reason(session: Session, manifest_docs: dict[str, dict], model: str, rows: list) -> str | None:
    if session.execute(text("SELECT count(*) FROM ai.reference_chunks_ctx")).scalar():
        return "새 표가 비어 있지 않음 — 다시 적재하지 않음"
    if not rows:
        return "지금 표가 비어 있음"
    models = set(session.execute(text("SELECT DISTINCT embedding_model FROM ai.reference_chunks")).scalars())
    if models != {model}:
        return f"지금 표 embedding_model {len(models)}종 — 설정 모델 하나여야"
    for r in rows:
        meta = manifest_docs.get(r.doc_id)
        if meta is None or (r.doc_title, r.publisher, r.year) != (
            meta["title"],
            meta.get("publisher"),
            meta.get("year"),
        ):
            return f"지금 표 메타 ≠ manifest ({r.doc_id})"
    return None


def ingest_ctx(session: Session, embedder: EmbeddingClient, manifest_docs: dict[str, dict]) -> int:
    """새 표에 넣은 행 수. 거절·실패는 예외(롤백 — INSERT 0)."""
    model = embedder.model.strip()
    try:
        _lock(session)
        rows = session.execute(_READ).all()
        if reason := refuse_reason(session, manifest_docs, model, rows):
            raise ValueError(reason)
        meta = {d: manifest_docs[d] for d in {r.doc_id for r in rows}}
        texts = [
            context_text(context_header(meta[r.doc_id]["title"], meta[r.doc_id].get("publisher"),
                                        meta[r.doc_id].get("year"), r.page), r.text)
            for r in rows
        ]  # fmt: skip
        vectors = embedder.embed(texts)
        if len(vectors) != len(rows):
            raise RetrievalUnavailable("embedding count mismatch")
        values = [
            {**r._asdict(), "embedding": str(v), "embedding_model": model}
            for r, v in zip(rows, vectors, strict=True)
        ]
        session.execute(_INSERT, values)
        session.commit()
    except Exception:
        session.rollback()
        raise
    log.info("corpus_ctx_loaded", extra={"chunks": len(values)})
    return len(values)


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    manifest = json.loads((settings.corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    docs = {d["id"]: d for d in manifest["documents"]}
    with Session(get_engine()) as session:
        print(ingest_ctx(session, make_embedding_client(settings), docs))


if __name__ == "__main__":
    main()
