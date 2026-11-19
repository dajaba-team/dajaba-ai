"""SCRUM-275 빈칸만 채우기 — 지금 경로 1차 결과 뒤 남는 칸 (docs/str/10 "빈칸만 채우기" 흐름).

release(DB 연결 반납, SCRUM-122) → (b)(c) 임베딩 + ES 키워드(외부 호출) → PG 2차(필터 끔 후보 · (a) cosine)
→ RRF → 1차 `chunk_id` 건너뜀 → 남는 칸. PG 2차는 `open_session()` 이 주는 **별도 짧은 세션**에서만 —
실패하면 그 세션만 닫히고 공유(초안) 세션은 1차 상태 그대로(추가 검토 1 high). 채운 칸 `score` = (a) 기준 cosine. 키워드 실패 → 벡터만,
그 밖 실패 → 1차 결과만(fail-open, 이유 낱말만 로그 — 검색어·본문 없음).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient
from aml_ai.shared.schemas.str import Facts, Reference
from aml_ai.str.domain.constants import MIN_SIMILARITY, RAG_CANDIDATES
from aml_ai.str.domain.rag_fill import fill_order
from aml_ai.str.domain.rag_fusion import Candidate, rrf_fuse
from aml_ai.str.domain.rag_queries import build_queries, keyword_queries
from aml_ai.str.infrastructure.keyword_search import KeywordSearch, KeywordUnavailable

log = logging.getLogger(__name__)

Search = Callable[[Session, list[float]], list[Reference]]
Cosines = Callable[[Session, list[float], list[str]], list[Reference]]
OpenSession = Callable[[], AbstractContextManager[Session]]


def fill_gaps(
    facts: Facts,
    vec_a: list[float],
    first: list[Reference],
    *,
    k: int,
    embedder: EmbeddingClient,
    keyword: KeywordSearch | None,
    release: Callable[[], None],
    unfiltered: Search,
    cosines: Cosines,
    open_session: OpenSession,
) -> list[Reference]:
    try:
        release()
        extra = [q.text for q in build_queries(facts)[1:]]  # (a) 는 이미 임베딩함
        extra_vectors = embedder.embed(extra) if extra else []
        if len(extra_vectors) != len(extra):
            raise RetrievalUnavailable("embedding count mismatch")
        keyword_lists = _keyword_lists(keyword, facts)
        with open_session() as session:
            lists = [_ranked(unfiltered(session, vec)) for vec in [vec_a, *extra_vectors]] + keyword_lists
            order = fill_order([r.chunk_id for r in first], [f.chunk_id for f in rrf_fuse(lists)])
            by_id = {r.chunk_id: r for r in cosines(session, vec_a, order)} if order else {}
        filled = [by_id[c] for c in order if c in by_id and by_id[c].score >= MIN_SIMILARITY]
        return first + filled[: k - len(first)]
    except Exception as exc:  # noqa: BLE001 — 합치기 층 어떤 실패든 지금 결과는 지킴(fail-open)
        log.warning("rag_fill_failed", extra={"reason": type(exc).__name__})
        return first


def _ranked(refs: list[Reference]) -> list[Candidate]:
    return [Candidate(r.chunk_id, rank, r.score) for rank, r in enumerate(refs, 1)]


def _keyword_lists(keyword: KeywordSearch | None, facts: Facts) -> list[list[Candidate]]:
    """언어별 키워드 목록(순위만 — cosine 은 0.0, 점수는 나중에 (a) cosine 으로). 첫 실패에서 전부 포기."""
    if keyword is None:
        return []
    lists: list[list[Candidate]] = []
    for query in keyword_queries(facts):
        try:
            ids = keyword.search(query.lang, query.text, RAG_CANDIDATES)
        except KeywordUnavailable as exc:
            log.warning("keyword_unavailable", extra={"reason": exc.reason})
            return []
        lists.append([Candidate(chunk_id, rank, 0.0) for rank, chunk_id in enumerate(ids, 1)])
    return lists
