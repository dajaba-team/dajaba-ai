"""SCRUM-308 ② 리랭커 판정 결과 조립 — 지표(`judge`)·질의 기록·설정 (실행 모듈 `rag_eval_v3_rerank_live` 가 씀). 원문 0."""

from __future__ import annotations

from pathlib import Path

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.str import Reference
from aml_ai.str.domain.constants import MIN_SIMILARITY, RAG_CANDIDATES
from aml_ai.str.domain.constants_rag_query import RAG_RERANK_MAX_TOKENS
from aml_ai.str.infrastructure.retriever_rerank import rerank_model, rerank_prompt
from tests.str import rag_eval_v3_cutoff_guard as cg
from tests.str import rag_eval_v3_rerank_support as rs

REPO = Path(__file__).resolve().parents[2]


def judge(queries: list[dict], cands: dict, rounds: list[dict], answers: dict) -> tuple[dict, list[dict]]:
    """p95 = 정답 있는 질의의 호출 시간 · 실패율 = 회차 전체 리랭커 대상(후보 ≥ 2) 중 폴백(추가 검토 1)."""
    base = rs.metrics(
        [{"typology": q["typology"], "top": [r.chunk_id for r in cands[q["id"]]]} for q in queries], answers
    )
    per_round = []
    for rnd in rounds:
        rr = rs.metrics([{"typology": q["typology"], "top": rnd[q["id"]]["order"]} for q in queries], answers)
        ms = [
            rnd[q["id"]]["ms"]
            for q in queries
            if answers.get(q["typology"] or "") and rnd[q["id"]]["ms"] is not None
        ]
        targets = [r for r in rnd.values() if r["called"]]
        result = rs.round_verdict(base, rr, ms, sum(r["failed"] is not None for r in targets), len(targets))
        per_round.append({"metrics": rr, **result})
    return base, per_round


def record(q: dict, refs: list[Reference], positions: dict, rounds: list[dict]) -> dict:
    return {
        "id": q["id"], "typology": q["typology"], "uses": q["uses"],
        "candidates": [{"rank": i, "chunk_id": r.chunk_id, **{k: positions[r.chunk_id][k] for k in ("doc_id", "page", "pos")},
                        "cosine": round(r.score, 6)} for i, r in enumerate(refs, 1)],
        "rounds": [rnd[q["id"]] for rnd in rounds],
    }  # fmt: skip


def configuration(settings: Settings, digests: dict, prepared: dict, rounds: list[dict], dry: bool) -> dict:
    return {
        "dry": dry, "criteria_commit": cg.CRITERIA_COMMIT,
        "head": cg._git(REPO, "rev-parse", "HEAD").stdout.decode().strip(),  # noqa: SLF001
        **{f"{Path(p).stem}_sha256": d for p, d in digests.items()},
        "rerank_v1_sha256": rerank_prompt()[2],  # 실행에 쓴 바이트의 해시(동결 대조 끝난 것)
        "embedding_model": settings.embedding_model.strip(), "rerank_model": "dry" if dry else rerank_model(settings),
        "reasoning_effort": settings.llm_reasoning_effort, "temperature_supported": settings.llm_temperature_supported,
        "constants": {"RAG_CANDIDATES": RAG_CANDIDATES, "MIN_SIMILARITY": MIN_SIMILARITY,
                      "RAG_RERANK_MAX_TOKENS": RAG_RERANK_MAX_TOKENS, "RAG_RERANK_TIMEOUT_S": settings.rag_rerank_timeout_s},
        "embedding_batches": len(prepared), "llm_calls": sum(r["ms"] is not None for rnd in rounds for r in rnd.values()),
    }  # fmt: skip
