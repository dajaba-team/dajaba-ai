"""SCRUM-308-3 청크 맥락 기동 검사 — 새 표 = 지금 표일 때만 새 표를 씀 (docs/str/10 "청크 맥락").

켬 + v4 일 때만. 읽기 전용 대조: 새 표 있음 · 행 수 같고 0 아님 · `chunk_id` 집합 · 청크별 문서·쪽·태그·본문·`content_hash` ·
머리말 메타(제목·발행처·연도)·section·lang(추가 검토 1) · `embedding_model` 두 표 모두 설정 값 1종 · 벡터 차원. 다르면 기동 실패(RuntimeError). **DB 접속 실패는 기동을 막지 않고
지금 표**(경고 1줄 `chunk_context_unverified`) — 그 프로세스는 재시작 전까지 지금 표. 비유한 성분은 pgvector 가 넣을 때 거절.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.exc import DisconnectionError, InterfaceError, OperationalError
from sqlalchemy.orm import Session

from aml_ai.shared import chunk_context_state
from aml_ai.shared.config import Settings

log = logging.getLogger(__name__)

_DIFF = text(
    "SELECT count(*) FROM ai.reference_chunks a FULL JOIN ai.reference_chunks_ctx b USING (chunk_id) "
    "WHERE a.chunk_id IS NULL OR b.chunk_id IS NULL OR a.doc_id IS DISTINCT FROM b.doc_id "
    "OR a.page IS DISTINCT FROM b.page OR a.typologies IS DISTINCT FROM b.typologies "
    "OR a.text IS DISTINCT FROM b.text OR a.content_hash IS DISTINCT FROM b.content_hash "
    "OR a.doc_title IS DISTINCT FROM b.doc_title OR a.publisher IS DISTINCT FROM b.publisher "
    "OR a.year IS DISTINCT FROM b.year OR a.section IS DISTINCT FROM b.section OR a.lang IS DISTINCT FROM b.lang"
)


def ctx_table_problem(session: Session, model: str, dim: int) -> str | None:
    """새 표가 지금 표와 다르면 이유(낱말·개수만), 같으면 None. 같은 세션 = 같은 스냅샷이면 하네스도 이걸 씀."""
    if session.execute(text("SELECT to_regclass('ai.reference_chunks_ctx')")).scalar() is None:
        return "새 표 없음(마이그레이션 0007)"
    cur, ctx = session.execute(
        text(
            "SELECT (SELECT count(*) FROM ai.reference_chunks), (SELECT count(*) FROM ai.reference_chunks_ctx)"
        )
    ).one()
    if not ctx or cur != ctx:
        return f"새 표 행 수 {ctx} ≠ 지금 표 {cur}"
    if diff := session.execute(_DIFF).scalar():
        return f"새 표와 지금 표가 다른 청크 {diff}개(chunk_id·문서·쪽·태그·본문·머리말 메타)"
    for table in ("ai.reference_chunks", "ai.reference_chunks_ctx"):
        models = set(session.execute(text(f"SELECT DISTINCT embedding_model FROM {table}")).scalars())
        if models != {model.strip()}:
            return f"{table} embedding_model {len(models)}종 — 설정 모델 하나여야"
    bad = session.execute(
        text("SELECT count(*) FROM ai.reference_chunks_ctx WHERE vector_dims(embedding) <> :dim"),
        {"dim": dim},
    ).scalar()
    return f"새 표 벡터 차원 다른 행 {bad}" if bad else None


def verify_on_startup(settings: Settings, open_session: Callable[[], Session]) -> None:
    """기동 때 한 번 — 결과를 `chunk_context_state` 에. 끔이면 대조 안 하고 False."""
    chunk_context_state.set_verified(False)
    if not settings.rag_chunk_context_active:
        return
    try:
        with open_session() as session:
            problem = ctx_table_problem(session, settings.embedding_model, settings.embedding_dim)
    except (OperationalError, InterfaceError, DisconnectionError):
        log.warning("chunk_context_unverified")  # 지금 표로 — 재시작 전까지
        return
    if problem:
        raise RuntimeError(f"RAG_CHUNK_CONTEXT_ENABLED — {problem}")
    chunk_context_state.set_verified(True)
