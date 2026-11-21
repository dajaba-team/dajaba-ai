"""RAG 검색 (docs/str/10). 기본은 질의 한 번, 평가용 다중 질의는 RRF로 합친다.

enabled=False (RAG_ENABLED) 면 항상 [] — 안건 22 되돌림 조건의 스위치.
gap_fill=True (SCRUM-275, v4 만) 면 한 번 찾기 결과가 1~k-1 건일 때 남는 칸만 `retriever_fill` 로 채움.
fill_session = 채우기 PG 2차용 별도 세션 팩토리(초안은 draft_service 가 주입). 없으면 공유 세션 — 테스트·하네스용.
reranker (SCRUM-308-2, v4 만) 가 있으면 한 번 찾기 후보를 RAG_CANDIDATES 로 받아 `retriever_rerank` 로 다시 줄 세운 앞 k.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient
from aml_ai.shared.schemas.str import Facts, Reference
from aml_ai.str.domain.constants import (
    MIN_SIMILARITY,
    RAG_CANDIDATES,
    RAG_MULTI_QUERY,
    RAG_TOP_K,
    REFERENCE_TEXT_MAX_CHARS,
)
from aml_ai.str.domain.constants_rag_query import QUERY_KINDS
from aml_ai.str.domain.rag_fill import needs_fill
from aml_ai.str.domain.rag_fusion import Candidate, rrf_fuse
from aml_ai.str.domain.rag_queries import (
    TYPOLOGY_KO as TYPOLOGY_KO,
)
from aml_ai.str.domain.rag_queries import (
    TYPOLOGY_PATTERN_EN as TYPOLOGY_PATTERN_EN,
)
from aml_ai.str.domain.rag_queries import (
    build_queries,
)
from aml_ai.str.domain.rag_queries import (
    build_query as build_query,
)
from aml_ai.str.domain.rag_rerank import rerank_query
from aml_ai.str.infrastructure.keyword_search import KeywordSearch
from aml_ai.str.infrastructure.retriever_fill import fill_gaps
from aml_ai.str.infrastructure.retriever_rerank import Reranker, rerank_first


class Retriever:
    def __init__(
        self,
        session: Session,
        embedder: EmbeddingClient,
        *,
        enabled: bool,
        k: int = RAG_TOP_K,
        multi_query: bool = RAG_MULTI_QUERY,
        typology_filter: bool = True,
        query_kinds: tuple[str, ...] = QUERY_KINDS,
        gap_fill: bool = False,
        keyword: KeywordSearch | None = None,
        release: Callable[[], None] | None = None,
        fill_session: Callable[[], AbstractContextManager[Session]] | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._s = session
        self._embed = embedder
        self._enabled = enabled
        self._k = k
        self._multi_query = multi_query
        self._typology_filter = typology_filter
        self._query_kinds = query_kinds
        self._gap_fill = gap_fill
        self._keyword = keyword
        self._release = release or (lambda: None)
        self._fill_session = fill_session or (lambda: nullcontext(self._s))
        self._reranker = reranker

    def retrieve(self, facts: Facts) -> list[Reference]:
        if not self._enabled or facts.typology is None:
            return []
        if not self._multi_query:
            vec = self._embed.embed([build_query(facts)])[0]
            first = self._first(vec, facts)
            if not self._gap_fill or not needs_fill(len(first), self._k):
                return first
            return fill_gaps(
                facts, vec, first, k=self._k, embedder=self._embed, keyword=self._keyword, release=self._release,
                unfiltered=lambda s, v: self._candidates(v, None, limit=RAG_CANDIDATES, typology_filter=False, session=s),
                cosines=lambda s, v, ids: self._cosines(v, ids, session=s), open_session=self._fill_session,
            )  # fmt: skip
        queries = build_queries(facts, self._query_kinds)
        vectors = self._embed.embed([q.text for q in queries])
        if len(vectors) != len(queries):
            raise RetrievalUnavailable("embedding count mismatch")
        return self._multi_search(vectors, facts.typology.value)

    def _multi_search(self, vectors: list[list[float]], typology: str) -> list[Reference]:
        lists: list[list[Candidate]] = []
        refs: dict[str, Reference] = {}
        for vec in vectors:
            candidates = self._candidates(
                vec, typology, limit=RAG_CANDIDATES, typology_filter=self._typology_filter
            )
            lists.append([Candidate(r.chunk_id, rank, r.score) for rank, r in enumerate(candidates, 1)])
            refs.update((r.chunk_id, r) for r in candidates)
        return [
            refs[f.chunk_id].model_copy(update={"score": f.cosine})
            for f in rrf_fuse(lists)
            if f.cosine >= MIN_SIMILARITY
        ][: self._k]

    def _first(self, vec: list[float], facts: Facts) -> list[Reference]:
        """한 번 찾기 결과 — 리랭커 없으면 지금 그대로(후보 limit k), 있으면 후보 RAG_CANDIDATES → 다시 줄 세운 앞 k."""
        typology = facts.typology.value if facts.typology else None
        if self._reranker is None:
            return self._search(vec, typology)
        refs = self._search(vec, typology, limit=RAG_CANDIDATES)
        return rerank_first(self._reranker, rerank_query(facts), refs, k=self._k, release=self._release)

    def _search(self, vec: list[float], typology: str | None, limit: int | None = None) -> list[Reference]:
        if typology is None:
            return []
        return [
            r
            for r in self._candidates(
                vec, typology, limit=limit or self._k, typology_filter=self._typology_filter
            )
            if r.score >= MIN_SIMILARITY
        ]

    def _candidates(
        self,
        vec: list[float],
        typology: str | None,
        *,
        limit: int,
        typology_filter: bool,
        session: Session | None = None,
    ) -> list[Reference]:
        # 같은 임베딩 모델 행만(검토 5 — 차원이 같은 다른 모델 벡터와 섞지 않음)
        predicate = "WHERE embedding_model = :model " + (
            "AND typologies @> ARRAY[:ty]::text[] " if typology_filter else ""
        )
        params = {"vec": str(vec), "k": limit, "cand": RAG_CANDIDATES, "model": self._embed.model}
        if typology_filter:
            params["ty"] = typology
        try:
            db = session or self._s
            with db.begin_nested():
                db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
                rows = db.execute(
                    text(
                        "WITH r AS MATERIALIZED ("
                        "  SELECT chunk_id, doc_id, doc_title, page, text, "
                        "         embedding <=> CAST(:vec AS vector) AS d "
                        "  FROM ai.reference_chunks "
                        + predicate
                        + "  ORDER BY embedding <=> CAST(:vec AS vector) "
                        "  LIMIT :cand"
                        ") "
                        "SELECT chunk_id, doc_id, doc_title, page, text, 1 - d AS score "
                        "FROM r ORDER BY d + 0, chunk_id LIMIT :k"  # 동점은 chunk_id — LIMIT 3 = LIMIT 10 앞 셋(검토 6)
                    ),
                    params,
                ).all()
        except SQLAlchemyError as exc:
            raise RetrievalUnavailable("rag search failed") from exc
        return [_reference(row) for row in rows if row.score is not None]

    def _cosines(
        self, vec: list[float], chunk_ids: list[str], *, session: Session | None = None
    ) -> list[Reference]:
        """SCRUM-275 — 채울 후보의 (a) 기준 cosine. DB 에 없는 chunk_id 는 빠짐. 실패해도 세션은 savepoint 로 복구."""
        try:
            db = session or self._s
            with db.begin_nested():
                rows = db.execute(
                    text(
                        "SELECT chunk_id, doc_id, doc_title, page, text, "
                        "       1 - (embedding <=> CAST(:vec AS vector)) AS score "
                        "FROM ai.reference_chunks WHERE chunk_id = ANY(:ids) AND embedding_model = :model"
                    ),
                    {"vec": str(vec), "ids": list(chunk_ids), "model": self._embed.model},
                ).all()
        except SQLAlchemyError as exc:
            raise RetrievalUnavailable("rag cosine failed") from exc
        return [_reference(row) for row in rows if row.score is not None]


def _reference(row) -> Reference:  # noqa: ANN001 — SQLAlchemy Row
    return Reference(
        chunk_id=row.chunk_id,
        doc_id=row.doc_id,
        doc_title=row.doc_title,
        page=row.page,
        score=float(row.score),
        text=(row.text or "")[:REFERENCE_TEXT_MAX_CHARS],
    )
