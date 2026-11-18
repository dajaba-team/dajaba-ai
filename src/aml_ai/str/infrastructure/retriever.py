"""RAG 검색 (docs/str/10). 기본은 질의 한 번, 평가용 다중 질의는 RRF로 합친다.

enabled=False (RAG_ENABLED) 면 항상 [] — 안건 22 되돌림 조건의 스위치.
"""

from __future__ import annotations

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
    ) -> None:
        self._s = session
        self._embed = embedder
        self._enabled = enabled
        self._k = k
        self._multi_query = multi_query
        self._typology_filter = typology_filter
        self._query_kinds = query_kinds

    def retrieve(self, facts: Facts) -> list[Reference]:
        if not self._enabled or facts.typology is None:
            return []
        if not self._multi_query:
            vec = self._embed.embed([build_query(facts)])[0]
            return self._search(vec, facts.typology.value)
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

    def _search(self, vec: list[float], typology: str | None) -> list[Reference]:
        if typology is None:
            return []
        return [
            r
            for r in self._candidates(vec, typology, limit=self._k, typology_filter=self._typology_filter)
            if r.score >= MIN_SIMILARITY
        ]

    def _candidates(
        self, vec: list[float], typology: str | None, *, limit: int, typology_filter: bool
    ) -> list[Reference]:
        predicate = "WHERE typologies @> ARRAY[:ty]::text[] " if typology_filter else ""
        params = {"vec": str(vec), "k": limit, "cand": RAG_CANDIDATES}
        if typology_filter:
            params["ty"] = typology
        try:
            with self._s.begin_nested():
                self._s.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
                rows = self._s.execute(
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
                        "FROM r ORDER BY d + 0 LIMIT :k"
                    ),
                    params,
                ).all()
        except SQLAlchemyError as exc:
            raise RetrievalUnavailable("rag search failed") from exc
        return [
            Reference(
                chunk_id=row.chunk_id,
                doc_id=row.doc_id,
                doc_title=row.doc_title,
                page=row.page,
                score=float(row.score),
                text=(row.text or "")[:REFERENCE_TEXT_MAX_CHARS],
            )
            for row in rows
            if row.score is not None
        ]
