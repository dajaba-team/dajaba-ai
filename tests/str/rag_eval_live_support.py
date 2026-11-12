"""SCRUM-126 ★L-1 — RAG 검색 평가 공용 (metrics·overlap·queries 조립, rag_eval_live 에서 분리)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from tools.rag_eval import (
    overlap_rate,
    resolve_expected,
    same_typology_jaccard,
    scored_metrics,
)

from aml_ai.shared.infrastructure.embedding_client import make_embedding_client
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure import retriever as retriever_mod
from aml_ai.str.infrastructure.retriever import Retriever

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "str" / "fixtures" / "facts_fan_in.json"
MANIFEST = REPO / "corpus" / "manifest.json"


def build_facts(q: dict[str, Any]) -> Facts:
    base = json.loads(FIXTURE.read_text(encoding="utf-8"))
    base["typology"] = q["typology"]
    base["model_signals"] = q["model_signals"]
    if base.get("customer"):
        base["customer"]["industry"] = q["industry"]
    return Facts.model_validate(base)


def verify_expected(session: Any, expected_sets: dict) -> None:
    all_ids: set[str] = set()
    for grp in expected_sets.values():
        all_ids.update(grp["2"])
        all_ids.update(grp["1"])
    rows = (
        session.execute(
            text("SELECT chunk_id FROM ai.reference_chunks WHERE chunk_id = ANY(:ids)"),
            {"ids": list(all_ids)},
        )
        .scalars()
        .all()
    )
    missing = all_ids - set(rows)
    if missing:
        print(f"[FAIL] 정답 chunk_id {len(missing)}개가 DB 에 없음 — retrieval_eval.json 재적재 필요:")
        for cid in sorted(missing):
            print(f"  - {cid}")
        raise SystemExit("exit on missing chunk_ids")


def retrieve_all(eval_data: dict, session: Any, settings: Any) -> list[dict]:
    embedder = make_embedding_client(settings)
    retriever = Retriever(session, embedder, enabled=True)
    saved = retriever_mod.MIN_SIMILARITY
    retriever_mod.MIN_SIMILARITY = 0.0  # 측정 전용 override — 상수 자체는 안 바꿈
    try:
        out: list[dict] = []
        for q in eval_data["queries"]:
            refs = retriever.retrieve(build_facts(q))
            out.append({"query": q, "refs": refs})
    finally:
        retriever_mod.MIN_SIMILARITY = saved
    return out


def _expected_score(cid: str, expected: dict[str, set[str]] | None) -> int:
    if expected is None:
        return 0
    if cid in expected["2"]:
        return 2
    if cid in expected["1"]:
        return 1
    return 0


def metrics_for_threshold(all_results: list[dict], eval_data: dict, thr: float) -> dict:
    by_typo: dict[str, list[dict]] = {}
    empty_correct = empty_total = 0
    for row in all_results:
        q = row["query"]
        top_ids = [r.chunk_id for r in row["refs"] if r.score >= thr]
        exp = resolve_expected(q["expected_set"], expected_sets=eval_data["expected_sets"])
        if exp is None:
            empty_total += 1
            empty_correct += int(not top_ids)
            continue
        exp_lists = {"2": list(exp["2"]), "1": list(exp["1"])}
        by_typo.setdefault(q["typology"], []).append(
            {
                "strict": scored_metrics(top_ids, exp_lists, mode="strict"),
                "wide": scored_metrics(top_ids, exp_lists, mode="wide"),
            }
        )
    out: dict[str, Any] = {}
    keys = ("hit", "precision", "recall")
    for ty, scores in by_typo.items():
        n = len(scores)
        out[ty] = {
            "strict": {k: sum(s["strict"][k] for s in scores) / n for k in keys},
            "wide": {k: sum(s["wide"][k] for s in scores) / n for k in keys},
            "n_queries": n,
        }
    if by_typo:
        out["macro"] = {
            "strict": {k: sum(out[ty]["strict"][k] for ty in by_typo) / len(by_typo) for k in keys},
            "wide": {k: sum(out[ty]["wide"][k] for ty in by_typo) / len(by_typo) for k in keys},
        }
    out["empty_set_correct"] = f"{empty_correct}/{empty_total}"
    return out


def overlap_and_jaccard(all_results: list[dict], session: Any) -> dict:
    """top-3 겹침 쌍 수 + 같은 유형 질의 Jaccard.

    청크 겹침은 앞 청크 끝·뒤 청크 처음이라 `REFERENCE_TEXT_MAX_CHARS=600` 로 잘린 `r.text` 로는
    못 잡음(9761a3b1·d994051 대표). `chunk_id` 로 `ai.reference_chunks.text` **전문** 을 다시 조회.
    """
    query_tops: dict[str, tuple[list[str], str | None]] = {}
    pairs_total = pairs_possible = 0
    for row in all_results:
        q = row["query"]
        top_ids = [r.chunk_id for r in row["refs"]]
        query_tops[q["id"]] = (top_ids, q["expected_set"])
        if not top_ids:
            continue
        db_rows = session.execute(
            text("SELECT chunk_id, text FROM ai.reference_chunks WHERE chunk_id = ANY(:ids)"),
            {"ids": top_ids},
        ).all()
        id_to_full = {r.chunk_id: r.text or "" for r in db_rows}
        chunks = [{"chunk_id": cid, "text": id_to_full.get(cid, "")} for cid in top_ids]
        pairs_total += overlap_rate(chunks, min_common_chars=100)
        n = len(chunks)
        pairs_possible += n * (n - 1) // 2
    return {
        "overlap_pairs": pairs_total,
        "overlap_pairs_possible": pairs_possible,
        "overlap_rate": pairs_total / pairs_possible if pairs_possible else 0.0,
        "same_typology_jaccard": same_typology_jaccard(query_tops),
    }


def retrieval_version(settings: Any) -> str:
    man_sha = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()[:8] if MANIFEST.exists() else "unknown"
    return f"{settings.embedding_model}@{man_sha}"


def assemble_queries_out(all_results: list[dict], eval_data: dict) -> list[dict]:
    out: list[dict] = []
    for row in all_results:
        q = row["query"]
        exp = resolve_expected(q["expected_set"], expected_sets=eval_data["expected_sets"])
        tops = [
            {
                "chunk_id": r.chunk_id,
                "doc_id": r.doc_id,
                "page": r.page,
                "score": round(r.score, 6),
                "expected_score": _expected_score(r.chunk_id, exp),
            }
            for r in row["refs"]
        ]
        out.append(
            {
                "id": q["id"],
                "typology": q["typology"],
                "expected_set": q["expected_set"],
                "model_signals": q["model_signals"],
                "industry": q["industry"],
                "top": tops,
            }
        )
    return out
