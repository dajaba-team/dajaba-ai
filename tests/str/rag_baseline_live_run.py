"""SCRUM-146 네 조건 실행. 외부 임베딩은 DB 세션을 열기 전에 끝낸다."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.infrastructure.embedding_client import make_embedding_client
from aml_ai.shared.schemas.str import Reference
from aml_ai.str.domain.constants import RAG_CANDIDATES
from aml_ai.str.domain.rag_queries import SearchQuery, build_queries
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.rag_baseline_live_db import ChunkRow, explain, full_ranking, readonly_session
from tests.str.rag_baseline_live_report import (
    condition_summary,
    expected_for,
    fuse_rankings,
    query_record,
    ranking_record,
    top_record,
)
from tests.str.rag_eval_live_support import build_facts


@dataclass
class PreparedEmbedding:
    queries: list[SearchQuery]
    vectors: list[list[float]]

    def embed(self, texts: list[str]) -> list[list[float]]:
        if texts != [q.text for q in self.queries]:
            raise ValueError("prepared embedding query mismatch")
        return self.vectors


def prepare(queries: list[SearchQuery], settings: Settings, dry: bool) -> PreparedEmbedding:
    texts = [q.text for q in queries]
    if dry:
        vectors = []
        for sentence in texts:
            digest = sha256(sentence.encode()).digest()
            vectors.append([digest[i % len(digest)] / 255 - 0.5 for i in range(settings.embedding_dim)])
    else:
        vectors = make_embedding_client(settings).embed(texts)
    if len(vectors) != len(texts):
        raise ValueError("prepared embedding count mismatch")
    return PreparedEmbedding(queries, vectors)


class RecordingRetriever(Retriever):
    def __init__(
        self,
        session: Session,
        prepared: PreparedEmbedding,
        multi: bool,
        filtered: bool,
        kinds: tuple[str, ...],
    ) -> None:
        super().__init__(
            session,
            prepared,
            enabled=True,
            k=RAG_CANDIDATES,
            multi_query=multi,
            typology_filter=filtered,
            query_kinds=kinds,
        )
        self.candidate_lists: list[list[Reference]] = []

    def _candidates(
        self, vec: list[float], typology: str | None, *, limit: int, typology_filter: bool
    ) -> list[Reference]:
        refs = super()._candidates(vec, typology, limit=limit, typology_filter=typology_filter)
        self.candidate_lists.append(refs)
        return refs


def search_record(
    prepared: PreparedEmbedding,
    retriever: RecordingRetriever,
    rows: dict[str, ChunkRow],
    seq: dict[str, int],
) -> list[dict]:
    return [
        {"kind": q.kind, "lang": q.lang, "query": q.text, "top10": top_record(refs, rows, seq)}
        for q, refs in zip(prepared.queries, retriever.candidate_lists, strict=True)
    ]


def full_records(
    session: Session,
    prepared: PreparedEmbedding,
    query: dict,
    data: dict,
    rows: dict[str, ChunkRow],
    seq: dict[str, int],
) -> dict:
    rankings = [full_ranking(session, vector) for vector in prepared.vectors]
    expected = expected_for(query, data)
    return {
        "per_query": {
            q.kind: ranking_record(ranking, expected, rows, seq)
            for q, ranking in zip(prepared.queries, rankings, strict=True)
        },
        "fused": ranking_record(fuse_rankings(rankings, rows), expected, rows, seq),
    }


def run_query(
    query: dict,
    data: dict,
    prepared: PreparedEmbedding,
    *,
    multi: bool,
    filtered: bool,
    kinds: tuple[str, ...],
    rows: dict[str, ChunkRow],
    seq: dict[str, int],
    plans: dict[str, list[str]],
) -> dict:
    with readonly_session() as session:
        retriever = RecordingRetriever(session, prepared, multi, filtered, kinds)
        refs = retriever.retrieve(build_facts(query))
        record = query_record(query, data, top_record(refs, rows, seq))
        record["searches"] = search_record(prepared, retriever, rows, seq)
        if not filtered:
            record["full_ranking"] = full_records(session, prepared, query, data, rows, seq)
        if filtered and query["typology"] not in plans:
            plans[query["typology"]] = explain(session, prepared.vectors[0], query["typology"])
    return record


def run_condition(
    data: dict,
    settings: Settings,
    *,
    dry: bool,
    multi: bool,
    filtered: bool,
    kinds: tuple[str, ...],
    rows: dict[str, ChunkRow],
    seq: dict[str, int],
    plans: dict[str, list[str]],
) -> dict:
    records = []
    query_count = 0
    for query in data["queries"]:
        queries = build_queries(build_facts(query), kinds if multi else ("a",))
        prepared = prepare(queries, settings, dry)
        query_count += len(queries)
        records.append(
            run_query(
                query,
                data,
                prepared,
                multi=multi,
                filtered=filtered,
                kinds=kinds,
                rows=rows,
                seq=seq,
                plans=plans,
            )
        )
    return {
        "multi_query": multi,
        "typology_filter": filtered,
        "queries": records,
        "embedding_calls": 0 if dry else len(records),
        "embedding_batches": len(records),
        "query_count": query_count,
        "summary": condition_summary(records),
    }
