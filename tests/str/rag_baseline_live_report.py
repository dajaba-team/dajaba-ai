"""SCRUM-146 기준선 기록 조립. 청크 원문이나 원문 지문을 출력하지 않는다."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from tools.rag_eval import resolve_expected, scored_metrics

from aml_ai.shared.schemas.str import Reference
from aml_ai.str.domain.rag_fusion import Candidate, rrf_fuse
from tests.str.rag_baseline_live_db import ChunkRow, RankedChunk
from tests.str.rag_baseline_support import (
    chunk_ref,
    cosine_summary,
    lang_count,
    rank_of,
    recall_at,
)


def expected_for(query: dict, data: dict) -> dict[str, set[str]] | None:
    return resolve_expected(query["expected_set"], expected_sets=data["expected_sets"])


def top_record(refs: list[Reference], rows: Mapping[str, ChunkRow], seq: dict[str, int]) -> list[dict]:
    return [{**chunk_ref(rows[r.chunk_id], seq), "cosine": r.score} for r in refs]


def query_record(query: dict, data: dict, top: list[dict]) -> dict:
    expected = expected_for(query, data)
    ids = [r["chunk_id"] for r in top]
    strict = expected["2"] if expected else set()
    scores = scored_metrics(ids[:3], expected, mode="strict") if expected else None
    return {
        "id": query["id"],
        "typology": query["typology"],
        "expected_set": query["expected_set"],
        "top10": top,
        "ko_count_top10": lang_count(top, "ko"),
        "hit@3": scores["hit"] if scores else None,
        "recall@3": recall_at(ids, strict, 3) if expected else None,
        "recall@10": recall_at(ids, strict, 10) if expected else None,
        "empty_top3_max_cosine": max((r["cosine"] for r in top[:3]), default=None) if not expected else None,
        "empty_top10_cosine_summary": cosine_summary([r["cosine"] for r in top]) if not expected else None,
    }


def condition_summary(records: list[dict]) -> dict:
    scored = [r for r in records if r["expected_set"] is not None]
    by_typology: dict[str, list[dict]] = defaultdict(list)
    for record in scored:
        by_typology[record["typology"]].append(record)
    metrics = ("hit@3", "recall@3", "recall@10")
    by_type = {
        ty: {metric: sum(r[metric] for r in group) / len(group) for metric in metrics}
        for ty, group in by_typology.items()
    }
    return {
        "n_scored": len(scored),
        "by_typology": by_type,
        "macro": {m: sum(t[m] for t in by_type.values()) / len(by_type) for m in metrics} if by_type else {},
        "query_mean": {m: sum(r[m] for r in scored) / len(scored) for m in metrics} if scored else {},
        "ko_count_top10": sum(r["ko_count_top10"] for r in records),
    }


def ranking_record(
    ranking: list[RankedChunk],
    expected: dict[str, set[str]] | None,
    rows: Mapping[str, ChunkRow],
    seq: dict[str, int],
) -> dict:
    ids = [r["chunk_id"] for r in ranking]
    languages = sorted({r["lang"] for r in ranking if r["lang"] is not None})
    return {
        "n": len(ranking),
        "expected_ranks": [
            {**chunk_ref(rows[cid], seq), "expected_score": score, "rank": rank_of(ids, cid)}
            for score in (2, 1)
            for cid in sorted(expected[str(score)] if expected else [])
        ],
        "cosine_by_lang": {
            lang: cosine_summary([r["cosine"] for r in ranking if r["lang"] == lang]) for lang in languages
        },
    }


def fuse_rankings(rankings: list[list[RankedChunk]], rows: Mapping[str, ChunkRow]) -> list[RankedChunk]:
    lists = [
        [Candidate(r["chunk_id"], rank, r["cosine"]) for rank, r in enumerate(ranking, 1)]
        for ranking in rankings
    ]
    return [RankedChunk(**rows[f.chunk_id], cosine=f.cosine) for f in rrf_fuse(lists)]
