"""SCRUM-308 ③ 청크 맥락 판정 실행 (손 실행, pytest 수집 X — 호스트, ES 안 씀). docs/str/10 308 절 ③ · "청크 맥락".

거절(기준 커밋·입력 바이트 — 308-2 `rag_eval_v3_rerank_guard` 재사용 · 실측이면 녹화 재생·빈 모델명) → 결과 경로 잠금 →
질의 문장을 검증한 픽스처 객체로 한 번 → (a) 임베딩 1회(유형 있는 질의만) → 읽기 전용 REPEATABLE READ 스냅샷 하나에서
DB 재확인(태그·위치·모델) + 새 표 = 지금 표(기동 검사와 같은 대조) + 두 표 초안 경로 후보 10 · 필터 끔 후보 10 + 재검사 행
→ 스냅샷 닫고 두 표 재임베딩 대조(65 + 65, cos ≥ 0.99) → 규칙 ③ → 임시 파일 → 원자 게시(`result_308_ctx.json`, 덮어쓰기 0).
`--dry`: 가짜 벡터 · 새 표가 없거나 다르면 지금 표로 대신 · `result_308_ctx_dry.json`(덮어씀) · 판정 안 함. 원문·검색어 문장 0.
"""

from __future__ import annotations

import argparse
import json
from contextlib import nullcontext
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings, get_settings
from aml_ai.str.domain.constants import MIN_SIMILARITY, RAG_CANDIDATES
from aml_ai.str.domain.constants_rag_query import CHUNK_CONTEXT_VERSION, REFERENCE_CTX_TABLE, REFERENCE_TABLE
from aml_ai.str.infrastructure.chunk_context_check import ctx_table_problem
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str import rag_eval_result_io as rio
from tests.str import rag_eval_v3_ctx_expect as ex
from tests.str import rag_eval_v3_ctx_recheck as pr
from tests.str import rag_eval_v3_ctx_support as cs
from tests.str import rag_eval_v3_cutoff_guard as cg
from tests.str import rag_eval_v3_hybrid_support as hs
from tests.str import rag_eval_v3_rerank_guard as rg
from tests.str import rag_eval_v3_rerank_live as rl
from tests.str import rag_eval_v3_rerank_recheck as recheck
from tests.str.rag_baseline_live_db import readonly_session
from tests.str.rag_eval_v3_hybrid_guard import db_problem
from tests.str.rag_eval_v3_hybrid_run import snapshot_session

REPO = Path(__file__).resolve().parents[2]


def rs_digest(stored: dict[str, tuple[str, list[float]]]) -> str:
    """표별 벡터 집합 sha256(chunk_id 순) — 판정한 벡터 기록(기동 검사는 벡터 값을 안 봄, 10_rag 한계)."""
    return sha256(json.dumps([[c, stored[c][1]] for c in sorted(stored)]).encode()).hexdigest()


def _search(session: Session, emb, table: str, typology: str | None, *, filtered: bool) -> list:  # noqa: ANN001
    if emb is None:
        return []
    refs = Retriever(session, emb, enabled=True, k=RAG_CANDIDATES, table=table)._candidates(  # noqa: SLF001
        emb.vectors[0], typology, limit=RAG_CANDIDATES, typology_filter=filtered)  # fmt: skip
    return [r for r in refs if r.score >= MIN_SIMILARITY]


def _checks(session: Session, loaded: dict, settings: Settings, expect: dict, *, dry: bool) -> str | None:
    """스냅샷 재확인 — 지금 표(태그·위치·모델·기대 매핑) · 새 표(기동 검사 대조 + 기대 매핑). dry 는 새 표 쪽만 건너뜀.
    반환 = 새 표를 못 쓰는 이유(dry 만 지금 표로 대신) — 실측이면 예외."""
    model = settings.embedding_model
    reason = db_problem(session, loaded[cg.CANDIDATES], loaded[rg.POSITIONS])[0]
    reason = (
        reason
        or rg.embedding_model_problem(session, model)
        or ex.table_problem(session, REFERENCE_TABLE, expect)
    )
    ctx_reason = ctx_table_problem(session, model, settings.embedding_dim)
    ctx_reason = ctx_reason or ex.table_problem(session, REFERENCE_CTX_TABLE, expect)
    if not ctx_reason and (same := pr.same_vector_rows(session)):  # 머리말 없는 벡터 복사(검토 3)
        ctx_reason = f"두 표 저장 벡터가 완전히 같은 행 {same}"
    if reason := reason or (None if dry else ctx_reason):
        raise ValueError(f"스냅샷 재확인 실패: {reason}")
    return ctx_reason


def fetch(queries: list[dict], prepared: dict, loaded: dict, settings: Settings, *, dry: bool) -> dict:
    """스냅샷 하나에서 재확인 + 두 표 후보(필터 켬·끔) + 재검사 행(기대 매핑에서 정한 대상). 실측이면 기대와 다르면 중단."""
    expect = ex.expected(loaded[ex.MANIFEST], loaded[rg.POSITIONS]["positions"])
    ids = sorted(expect)  # 재임베딩 대조 = 두 표 722 전부(검토 2)
    with snapshot_session() as session:
        ctx_reason = _checks(session, loaded, settings, expect, dry=dry)
        tables = {
            "current": REFERENCE_TABLE,
            "ctx": REFERENCE_CTX_TABLE if ctx_reason is None else REFERENCE_TABLE,
        }
        out = {
            f"{name}_{'on' if f else 'off'}": {
                q["id"]: _search(session, prepared.get(q["id"]), t, q["typology"], filtered=f)
                for q in queries
            }
            for name, t in tables.items()
            for f in (True, False)
        }
        model = settings.embedding_model
        out["stored"] = {"current": ex.stored(session, REFERENCE_TABLE, ids, model, expect)}
        out["stored"]["ctx"] = (
            {} if ctx_reason else ex.stored(session, REFERENCE_CTX_TABLE, ids, model, expect)
        )
        out["ctx_table"] = (
            REFERENCE_CTX_TABLE if ctx_reason is None else f"{REFERENCE_TABLE} (dry 대신 — {ctx_reason})"
        )
    return out


def _tops(cands: dict) -> dict[str, list[str]]:
    return {qid: [r.chunk_id for r in refs] for qid, refs in cands.items()}


def judge(queries: list[dict], got: dict, loaded: dict, *, dry: bool) -> dict:
    on, off = (
        hs.answer_sets(loaded[cg.CANDIDATES], filtered=True),
        hs.answer_sets(loaded[cg.CANDIDATES], filtered=False),
    )
    if leaks := cs.no_answer_leaks(_tops(got["current_on"]), queries, on):
        raise ValueError(f"정답 없는 질의에 지금 표 결과가 있음: {leaks}")
    table = {k: cs.metrics(_tops(got[k]), queries, on if k.endswith("_on") else off)
             for k in ("current_on", "ctx_on", "current_off", "ctx_off")}  # fmt: skip
    leaks = cs.no_answer_leaks(_tops(got["ctx_on"]), queries, on)
    return {"metrics": table, "verdict": cs.verdict(table["current_on"], table["ctx_on"], leaks, dry=dry)}


def evaluate(settings: Settings, loaded: dict, digests: dict, *, dry: bool) -> dict:
    queries = loaded[cg.QUERIES]["queries"]
    texts = rl.build_texts(queries, loaded)
    prepared = {qid: recheck.embed_query(t[0], settings, dry) for qid, t in texts.items()}
    got = fetch(queries, prepared, loaded, settings, dry=dry)
    judged = judge(queries, got, loaded, dry=dry)
    stored = got["stored"]
    corpus = {"skipped": "dry"} if dry else pr.paired_recheck(stored["current"], stored["ctx"], settings)
    if not dry and (reason := pr.paired_problem(corpus)):  # 두 벌로 가까운 쪽까지(검토 3)
        raise ValueError(reason)
    return {
        "_doc": "SCRUM-308 ③ 청크 맥락 — chunk_id·위치·cosine·지표만, 원문·검색어 문장 0 (docs/str/10 308 절 ③).",
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"), "dry": dry,
        "configuration": {
            "dry": dry, "criteria_commit": cg.CRITERIA_COMMIT,
            "head": cg._git(REPO, "rev-parse", "HEAD").stdout.decode().strip(),  # noqa: SLF001
            **{f"{Path(p).stem}_sha256": d for p, d in digests.items()},
            "embedding_model": settings.embedding_model, "chunk_context_version": CHUNK_CONTEXT_VERSION,
            "ctx_table": got["ctx_table"], "constants": {"RAG_CANDIDATES": RAG_CANDIDATES, "MIN_SIMILARITY": MIN_SIMILARITY},
            "query_embeddings": len(prepared), "recheck_chunks": {k: len(v) for k, v in got["stored"].items()},
            "vector_sha256": {k: rs_digest(v) for k, v in got["stored"].items()},
        },
        "corpus_recheck": corpus, **judged,
        "queries": [cs.record(q, got, loaded[rg.POSITIONS]["positions"]) for q in queries],
    }  # fmt: skip


def precheck(settings: Settings, loaded: dict | None, dry: bool) -> str | None:
    """외부 호출 전 — 실측 설정 · 스냅샷과 같은 대조(태그·위치·모델·기대 매핑 · 실측이면 새 표까지)."""
    if loaded is None:
        return None
    if not dry and settings.ai_llm_mock:
        return "AI_LLM_MOCK=true — 녹화 재생은 실측이 아님"
    if not settings.embedding_model:
        return "EMBEDDING_MODEL 이 비어 있음"
    expect = ex.expected(loaded[ex.MANIFEST], loaded[rg.POSITIONS]["positions"])
    with readonly_session() as session:
        try:
            _checks(session, loaded, settings, expect, dry=dry)
        except ValueError as exc:
            return str(exc)
    return None


def main(argv: list[str] | None = None, *, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="가짜 벡터 · 임베딩 0 · 판정 안 함")
    args = parser.parse_args(argv)
    settings = settings or get_settings()
    settings = settings.model_copy(
        update={"embedding_model": settings.embedding_model.strip()}
    )  # 한 번 정규화
    out = cs.DRY_RESULT_FILE if args.dry else cs.RESULT_FILE
    loaded, digests, reason = rg.refuse_before(REPO, None if args.dry else out)
    if loaded is not None and reason is None:  # 기대 태그·머리말 — 기준 커밋 manifest(검토 1)
        docs, mdigest, reason = ex.read_manifest(REPO, loaded[rg.POSITIONS])
        loaded, digests = {**loaded, ex.MANIFEST: docs}, {**digests, ex.MANIFEST: mdigest}
    if reason := reason or precheck(settings, loaded, args.dry):
        print(reason)
        return 2
    with nullcontext() if args.dry else rio.run_lock(out):
        if not args.dry and out.exists():  # 잠금 직전에 다른 실행이 게시 — 외부 호출 0 으로 끝
            print(f"결과 파일이 이미 있음({out.name})")
            return 2
        doc = evaluate(settings, loaded, digests, dry=args.dry)
        if leaks := hs.forbidden_keys(doc):
            raise ValueError(f"결과에 본문 키: {leaks[:3]}")
        text_out = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
        out.write_text(text_out, encoding="utf-8") if args.dry else rio.publish_new(out, text_out)
    m = doc["metrics"]
    print(json.dumps({"dry": args.dry, "verdict": doc["verdict"], "ctx_table": doc["configuration"]["ctx_table"],
                      "mean_precision3": {k: m[k]["mean_precision3"] for k in ("current_on", "ctx_on")}},
                     ensure_ascii=False))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
