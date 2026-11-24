"""초안 설정에 맞춰 참고자료 검색기를 조립한다 (docs/str/10)."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from aml_ai.shared import chunk_context_state
from aml_ai.shared.config import Settings
from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient
from aml_ai.shared.infrastructure.llm_client import LlmClient
from aml_ai.str.domain.constants_rag_query import REFERENCE_CTX_TABLE, REFERENCE_TABLE
from aml_ai.str.infrastructure.keyword_search import make_keyword_search
from aml_ai.str.infrastructure.retriever import Retriever
from aml_ai.str.infrastructure.retriever_rerank import safe_reranker


def build_retriever(
    session: Session,
    settings: Settings,
    llm: LlmClient,
    embedder: EmbeddingClient,
    *,
    release: Callable[[], None],
    clock: Callable[[], float],
) -> Retriever:
    fill = settings.rag_gap_fill_active
    return Retriever(
        session,
        embedder,
        clock=clock,
        enabled=settings.rag_enabled,
        gap_fill=fill,
        keyword=make_keyword_search(settings) if fill else None,
        release=release,
        fill_session=lambda: Session(bind=session.get_bind(), expire_on_commit=False),  # SCRUM-275 — 2차 전용
        reranker=safe_reranker(settings, llm) if settings.rag_rerank_active else None,  # SCRUM-308-2 — v4 만
        table=REFERENCE_CTX_TABLE if chunk_context_state.in_use(settings) else REFERENCE_TABLE,  # SCRUM-308-3
    )
