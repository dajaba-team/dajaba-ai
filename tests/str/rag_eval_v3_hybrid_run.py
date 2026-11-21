"""SCRUM-307 검색 실행 — 질의마다 임베딩·키워드 한 번, 조건 9개는 같은 벡터·같은 키워드 목록을 씀.

검색은 지금 코드를 부르기만: 벡터 목록 = `Retriever._candidates`(SQL 그대로) · 키워드 = `keyword_queries` +
`KeywordSearch.search` · 합치기 = `rrf_fuse` · 키워드로만 찾은 청크 cosine = `Retriever._cosines`((a) 기준).
`fill_gaps` 와 같은 순서·모양(벡터 목록 조합 순 → 키워드 en, ko). 외부 호출(임베딩·ES)은 DB 세션을 열기 전에 끝냄.
추가 검토 1·2: ES 응답 검사는 `rag_eval_v3_hybrid_es`(src 안 고침) · RRF 앞 10 을 먼저 고정한 뒤 cosine(키워드로만
찾은 청크 점수가 없거나 유한하지 않으면 중단, 유한한 음수는 그 순위에) · ES 시간은 질의마다 한 번 잼 · 9조건 PG 검색은
외부 호출이 끝난 뒤 읽기 전용 REPEATABLE READ 트랜잭션 하나(`snapshot_session`)에서 같은 스냅샷으로.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.db import get_engine
from aml_ai.str.domain.constants import RAG_CANDIDATES
from aml_ai.str.domain.rag_fusion import Candidate, rrf_fuse
from aml_ai.str.domain.rag_queries import build_queries, keyword_queries
from aml_ai.str.infrastructure.keyword_search import KeywordSearch
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.rag_baseline_live_run import PreparedEmbedding, prepare
from tests.str.rag_eval_v2_support import build_facts
from tests.str.rag_eval_v3_hybrid_support import TOP_RECALL, Condition

_MS = 1000
ALL_KINDS = ("a", "b", "c")


@dataclass
class Prepared:
    """질의 하나 — 벡터(종류별)·키워드 목록. 문장은 해시로만 밖에 나감."""

    query: dict[str, Any]
    embedding: PreparedEmbedding
    keyword_lists: list[list[str]] = field(default_factory=list)
    embed_ms: float = 0.0
    keyword_ms: float = 0.0

    def vectors(self, kinds: tuple[str, ...]) -> list[list[float]]:
        return [
            v for q, v in zip(self.embedding.queries, self.embedding.vectors, strict=True) if q.kind in kinds
        ]

    def vector_a(self) -> list[float] | None:
        found = self.vectors(("a",))
        return found[0] if found else None


def prepare_query(
    query: dict[str, Any], settings: Settings, keyword: KeywordSearch | None, dry: bool
) -> Prepared:
    facts = build_facts(query)
    queries = build_queries(facts, ALL_KINDS)
    started = time.perf_counter()
    embedding = prepare(queries, settings, dry) if queries else PreparedEmbedding([], [])
    out = Prepared(query, embedding, embed_ms=(time.perf_counter() - started) * _MS)
    if keyword is not None:  # 실패(KeywordUnavailable · PartialSearch)는 잡지 않음 — 실행 중단
        started = time.perf_counter()
        out.keyword_lists = [keyword.search(q.lang, q.text, RAG_CANDIDATES) for q in keyword_queries(facts)]
        out.keyword_ms = (time.perf_counter() - started) * _MS
    return out


def sentence_hashes(prepared: list[Prepared]) -> dict[str, str]:
    """검색어·키워드 문장 전체의 sha256 — 문장 자체는 결과에 안 남김."""
    vec = "\n".join(q.text for p in prepared for q in p.embedding.queries)
    kw = "\n".join(q.text for p in prepared for q in keyword_queries(build_facts(p.query)))
    return {"query_sentences_sha256": sha256(vec.encode()).hexdigest(),
            "keyword_sentences_sha256": sha256(kw.encode()).hexdigest()}  # fmt: skip


def fuse(vector_lists: list[list[tuple[str, float]]], keyword_lists: list[list[str]]) -> list[str]:
    """벡터 목록 [(chunk_id, cosine)] + 키워드 목록 [chunk_id] → RRF 순 chunk_id(키워드 cosine 0.0 — fill_gaps 와 같음)."""
    lists = [[Candidate(c, rank, cos) for rank, (c, cos) in enumerate(lst, 1)] for lst in vector_lists]
    lists += [[Candidate(c, rank, 0.0) for rank, c in enumerate(lst, 1)] for lst in keyword_lists]
    return [f.chunk_id for f in rrf_fuse(lists)]


@contextmanager
def snapshot_session() -> Iterator[Session]:
    """읽기 전용 REPEATABLE READ 트랜잭션 하나 — 안의 모든 조회가 같은 스냅샷."""
    with Session(get_engine()) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        yield session


def search(p: Prepared, cond: Condition, session: Session) -> tuple[list[tuple[str, float]], float]:
    """조건 하나 — RRF 앞 10 [(chunk_id, cosine)]·PG 조회·합치기 시간 ms. cosine = 벡터 목록 최대, 키워드로만 찾은 청크는 (a) 기준."""
    typology = p.query["typology"]
    vectors = p.vectors(cond.kinds)
    if (cond.filtered and typology is None) or not vectors:
        return [], 0.0
    started = time.perf_counter()
    retriever = Retriever(session, p.embedding, enabled=True, k=RAG_CANDIDATES)
    lists = [[(r.chunk_id, r.score) for r in retriever._candidates(  # noqa: SLF001 — 지금 SQL 그대로 부름
        v, typology, limit=RAG_CANDIDATES, typology_filter=cond.filtered)] for v in vectors]  # fmt: skip
    order = fuse(lists, p.keyword_lists if cond.keyword else [])[:TOP_RECALL]  # 앞 10 먼저 고정
    cosine = vector_cosines(lists)
    only_kw = [c for c in order if c not in cosine]
    vec_a = p.vector_a()
    if only_kw:
        found = retriever._cosines(vec_a, only_kw) if vec_a is not None else []  # noqa: SLF001
        cosine |= {r.chunk_id: r.score for r in found}
    if missing := [c for c in order if c not in cosine]:
        raise ValueError(f"키워드로만 찾은 청크 {len(missing)}개의 DB 점수가 없음 — ES·DB 불일치")
    if bad := [c for c in order if not math.isfinite(cosine[c])]:
        raise ValueError(f"top-10 cosine 이 유한하지 않음 {len(bad)}개 — 파일 쓰기 전 중단")
    return [(c, cosine[c]) for c in order], (time.perf_counter() - started) * _MS


def vector_cosines(lists: list[list[tuple[str, float]]]) -> dict[str, float]:
    """청크마다 여러 벡터 목록 중 최대 cosine(rrf_fuse 와 같음)."""
    cosine: dict[str, float] = {}
    for c, cos in (pair for lst in lists for pair in lst):
        cosine[c] = max(cos, cosine.get(c, cos))
    return cosine
