"""SCRUM-308 ② 리랭커 판정 실행 (손 실행, pytest 수집 X — 호스트, ES 안 씀). docs/str/10 308 절 ② · "리랭커".

거절(`rag_eval_v3_rerank_guard`, 실측이면 녹화 재생·모델·추론 설정까지) → 프롬프트 바이트 해시 대조 → 결과 경로 잠금 →
질의 문장을 한 번 만듦(픽스처 바이트 다시 대조) → (a) 임베딩(유형 있는 질의만) → 읽기 전용 REPEATABLE READ 스냅샷 하나에서
DB 재확인 + 초안 경로 후보 10 → 정답 없는 질의에 결과가 있으면 중단 → 같은 후보·같은 질의 문장으로 리랭커 2회 → 규칙 ②
→ 임시 파일 → 원자적 게시(`result_308_rerank.json`, 덮어쓰기 0). 리랭커 실패는 원래 순서로 세고 이유 낱말만.
`--dry`: 가짜 벡터 + 가짜 리랭커(뒤집기) · `result_308_rerank_dry.json`(덮어씀). 결과에 원문·프롬프트·검색어 문장 0.
"""

from __future__ import annotations

import argparse
import copy
import json
import time
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.schemas.str import Reference
from aml_ai.str.domain.constants import MIN_SIMILARITY, RAG_CANDIDATES
from aml_ai.str.domain.constants_rag_query import RERANK_MIN_CANDIDATES
from aml_ai.str.domain.rag_queries import build_query
from aml_ai.str.domain.rag_rerank import rerank_query
from aml_ai.str.infrastructure.retriever import Retriever
from aml_ai.str.infrastructure.retriever_rerank import (
    Reranker,
    RerankFailed,
    make_reranker,
    rerank_model,
    rerank_prompt,
)
from tests.str import rag_eval_result_io as rio
from tests.str import rag_eval_v3_cutoff_guard as cg
from tests.str import rag_eval_v3_hybrid_support as hs
from tests.str import rag_eval_v3_rerank_guard as rg
from tests.str import rag_eval_v3_rerank_recheck as recheck
from tests.str import rag_eval_v3_rerank_report as report
from tests.str import rag_eval_v3_rerank_support as rs
from tests.str.rag_baseline_live_db import readonly_session
from tests.str.rag_baseline_live_run import PreparedEmbedding
from tests.str.rag_eval_v2_support import facts_from_data
from tests.str.rag_eval_v3_hybrid_guard import db_problem
from tests.str.rag_eval_v3_hybrid_run import snapshot_session

REPO = Path(__file__).resolve().parents[2]
_MS = 1000


class DryReranker:
    """가짜 리랭커 — 후보를 뒤집음(LLM 0). 경로 점검용 — 이 결과로는 판정하지 않음(dry 판정 false 고정)."""

    def order_with_model(self, query: str, refs: list[Reference]) -> tuple[list[Reference], str]:
        return list(reversed(refs)), "dry"


def build_texts(queries: list[dict], fixtures: dict[str, dict]) -> dict[str, tuple[str, str | None]]:
    """질의마다 (임베딩 문장 (a), 리랭커 질의 또는 None) — 검증한 픽스처 객체의 복사본만으로(파일 재읽기 0, 추가 검토 2)."""
    out = {}
    for q in queries:
        if q["typology"]:
            facts = facts_from_data(copy.deepcopy(fixtures[f"{rg.FIXTURES_DIR}/{q['base']}"]), q)
            out[q["id"]] = (build_query(facts), rerank_query(facts))
    return out


def fetch_candidates(
    queries: list[dict], prepared: dict[str, PreparedEmbedding], loaded: dict, model: str
) -> tuple[dict, dict]:
    """스냅샷 하나에서 DB 재확인(태그·위치·임베딩 모델) + 초안 경로 후보 RAG_CANDIDATES(지금 SQL, `score >= MIN_SIMILARITY`)."""
    with snapshot_session() as session:
        reason = db_problem(session, loaded[cg.CANDIDATES], loaded[rg.POSITIONS])[0]
        if reason := reason or rg.embedding_model_problem(session, model):
            raise ValueError(f"스냅샷 재확인 실패: {reason}")
        out = {}
        for q in queries:
            emb = prepared.get(q["id"])
            refs = [] if emb is None else Retriever(session, emb, enabled=True, k=RAG_CANDIDATES)._candidates(  # noqa: SLF001
                emb.vectors[0], q["typology"], limit=RAG_CANDIDATES, typology_filter=True)  # fmt: skip
            out[q["id"]] = [r for r in refs if r.score >= MIN_SIMILARITY]
        typologies = sorted({q["typology"] for q in queries if q["typology"]})
        stored = recheck.filtered_rows(session, typologies, model)  # 순위와 무관한 유형 필터 전체(검토 5)
    return out, stored  # 저장 벡터·본문도 같은 스냅샷에서(재임베딩 대조는 스냅샷 닫은 뒤)


def run_round(reranker: Reranker, queries: list[dict], cands: dict, texts: dict) -> dict[str, dict]:
    """후보 ≥ 2 질의만 리랭커 — 타이머는 리랭커 호출만. 질의가 등록 목록 밖이면 호출 없이 원래 순서(폴백으로 셈)."""
    out = {}
    for q in queries:
        refs = cands[q["id"]]
        query = texts.get(q["id"], ("", None))[1]
        if len(refs) < RERANK_MIN_CANDIDATES:
            out[q["id"]] = {"order": [r.chunk_id for r in refs], "ms": None, "failed": None, "called": False,
                            "model": None, "responded": False}  # fmt: skip
            continue
        ordered, failed, ms, model, responded = refs, "unregistered_signal", None, None, False
        if query is not None:
            started = time.perf_counter()
            try:
                (ordered, model), failed = reranker.order_with_model(query, refs), None  # type: ignore[attr-defined]
                responded = True
            except Exception as exc:  # noqa: BLE001 — 실패는 원래 순서로 셈(②), 이유 낱말만
                failed = str(exc) if isinstance(exc, RerankFailed) else type(exc).__name__
                responded = bool(
                    getattr(exc, "response_received", False)
                )  # 본문을 받은 뒤의 실패(클라이언트 표시)
                model = getattr(exc, "response_model", None)
            ms = round((time.perf_counter() - started) * _MS, 1)
        out[q["id"]] = {"order": [r.chunk_id for r in ordered], "ms": ms, "failed": failed, "called": True,
                        "model": model, "responded": responded}  # fmt: skip
    return out


def evaluate(settings: Settings, loaded: dict, digests: dict, *, dry: bool) -> dict:
    queries, model = loaded[cg.QUERIES]["queries"], settings.embedding_model  # main 에서 한 번 정규화한 값
    texts = build_texts(queries, loaded)
    prepared = {qid: recheck.embed_query(t[0], settings, dry) for qid, t in texts.items()}
    cands, stored = fetch_candidates(queries, prepared, loaded, model)
    answers = hs.answer_sets(loaded[cg.CANDIDATES], filtered=True)
    if reason := rg.no_answer_problem(queries, cands, answers):
        raise ValueError(reason)
    corpus = (
        {"skipped": "dry"} if dry else recheck.recheck(stored, settings)
    )  # 리랭커 호출 전 입력 확인(검토 4)
    if not dry and (reason := recheck.recheck_problem(corpus)):
        raise ValueError(reason)
    reranker: Reranker = DryReranker() if dry else make_reranker(settings)
    rounds = [run_round(reranker, queries, cands, texts) for _ in range(rs.ROUNDS)]
    base, per_round = report.judge(queries, cands, rounds, answers)
    requested = "dry" if dry else rerank_model(settings)
    for rr, rnd in zip(per_round, rounds, strict=True):
        rr.update(
            requested_model=requested,
            response_models=rs.response_models(rnd),
        )
    return {
        "_doc": "SCRUM-308 ② 리랭커 — chunk_id·위치·cosine·순서·시간·지표만, 원문·프롬프트·검색어 문장 0 (docs/str/10 308 절 ②).",
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"), "dry": dry,
        "configuration": report.configuration(settings, digests, prepared, rounds, dry),
        "corpus_recheck": corpus, "baseline": base, "rounds": per_round, "verdict": rs.final_verdict(per_round, dry=dry),
        "queries": [report.record(q, cands[q["id"]], loaded[rg.POSITIONS]["positions"], rounds) for q in queries],
    }  # fmt: skip


def precheck(settings: Settings, loaded: dict | None, dry: bool) -> str | None:
    """외부 호출 전 — 실측 설정 · 프롬프트 바이트 해시(다르면 ValueError) · DB 태그·위치 · DB 임베딩 모델."""
    if loaded is None:
        return None
    if not dry and (reason := rg.real_mode_problem(settings)):
        return reason
    rerank_prompt()
    with readonly_session() as session:
        reason = db_problem(session, loaded[cg.CANDIDATES], loaded[rg.POSITIONS])[0]
        return reason or rg.embedding_model_problem(session, settings.embedding_model)


def main(argv: list[str] | None = None, *, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry", action="store_true", help="가짜 벡터 + 가짜 리랭커 · LLM·임베딩 0 · 판정 안 함"
    )
    args = parser.parse_args(argv)
    settings = settings or get_settings()
    settings = settings.model_copy(
        update={"embedding_model": settings.embedding_model.strip()}
    )  # 한 번 정규화(검토 3)
    out = rs.DRY_RESULT_FILE if args.dry else rs.RESULT_FILE
    loaded, digests, reason = rg.refuse_before(REPO, None if args.dry else out)
    if reason := reason or precheck(settings, loaded, args.dry):
        print(reason)
        return 2
    with nullcontext() if args.dry else rio.run_lock(out):
        if not args.dry and out.exists():  # 잠금 직전에 다른 실행이 게시 — 외부 호출 0 으로 끝(추가 검토 2)
            print(f"결과 파일이 이미 있음({out.name})")
            return 2
        doc = evaluate(settings, loaded, digests, dry=args.dry)
        if leaks := hs.forbidden_keys(doc):
            raise ValueError(f"결과에 본문 키: {leaks[:3]}")
        text = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
        out.write_text(text, encoding="utf-8") if args.dry else rio.publish_new(out, text)
    print(json.dumps({"dry": args.dry, "verdict": doc["verdict"],
                      "rounds": [{k: r[k] for k in ("gain", "p95_ms", "fail_rate", "hit_drops", "response_models")}
                                 for r in doc["rounds"]]}, ensure_ascii=False))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
