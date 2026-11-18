"""SCRUM-146 검색어 a/b 겹침 진단. 검색 조건별 호출 수와 별도로 센다."""

from __future__ import annotations

from aml_ai.shared.config import Settings
from aml_ai.str.domain.constants import RAG_CANDIDATES
from aml_ai.str.domain.rag_queries import build_queries
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.rag_baseline_live_db import ChunkRow, readonly_session
from tests.str.rag_baseline_live_report import expected_for, top_record
from tests.str.rag_baseline_live_run import PreparedEmbedding, prepare
from tests.str.rag_baseline_support import ab_overlap
from tests.str.rag_eval_live_support import build_facts


def overlap_record(
    query: dict,
    data: dict,
    prepared: PreparedEmbedding,
    rows: dict[str, ChunkRow],
    seq: dict[str, int],
) -> dict:
    expected = expected_for(query, data)
    item = {"id": query["id"]}
    with readonly_session() as session:
        retriever = Retriever(session, prepared, enabled=True)
        for filtered in (True, False):
            tops = [
                retriever._candidates(v, query["typology"], limit=RAG_CANDIDATES, typology_filter=filtered)
                for v in prepared.vectors
            ]
            overlap = ab_overlap(
                *[[r.chunk_id for r in top] for top in tops], expected["2"] if expected else set()
            )
            item["filter_on" if filtered else "filter_off"] = {
                key: [
                    top_record([next(r for r in tops[0] if r.chunk_id == cid)], rows, seq)[0] for cid in ids
                ]
                for key, ids in overlap.items()
            }
    return item


def overlap_diagnostics(
    data: dict,
    settings: Settings,
    *,
    dry: bool,
    rows: dict[str, ChunkRow],
    seq: dict[str, int],
) -> dict:
    # Independent a/b control, also when the retrieval combination excludes b.
    records = []
    query_count = batches = 0
    for query in data["queries"]:
        queries = [q for q in build_queries(build_facts(query)) if q.kind in ("a", "b")]
        if len(queries) < 2:
            records.append({"id": query["id"], "reason": "pattern_unavailable"})
            continue
        prepared = prepare(queries, settings, dry)
        query_count += len(queries)
        batches += 1
        records.append(overlap_record(query, data, prepared, rows, seq))
    return {
        "queries": records,
        "embedding_calls": 0 if dry else batches,
        "embedding_batches": batches,
        "query_count": query_count,
    }
