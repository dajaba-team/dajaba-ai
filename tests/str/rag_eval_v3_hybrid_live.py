"""SCRUM-307 하이브리드·다중 질의 판정 실행 (손 실행, pytest 수집 X — docs/str/10 "하이브리드·다중 질의 판정").

ES 는 호스트 포트가 없어 AI 컨테이너 안에서 — tests·tools·.git 읽기 전용, 결과 폴더 `tests/str/rag_eval_v3` 만 쓰기.
실행 전 거절 ①~⑥(`rag_eval_v3_hybrid_guard`) → 질의 34 임베딩·키워드 한 번씩 → 조건 9 검색(DB 읽기 전용) →
지표·규칙 ①②③ → `result_307.json`(배타 생성 — 덮어쓰기 0). 키워드(부분 응답 포함)·임베딩 실패는 중단(결과 파일 안 씀).
`--dry`: 가짜 벡터 · ES 끔 · ③④ 건너뜀 · `result_307_dry.json`(덮어씀). 결과에 원문·검색어 문장 0.
지연: `latency_ms` = PG 조회·합치기 + (키워드 켬이면) 그 질의의 ES 시간 · `pg_fuse_latency_ms` = PG 조회·합치기만.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.versioning import retrieval_version
from aml_ai.str.domain import constants
from tests.str import rag_eval_v3_hybrid_guard as guard
from tests.str import rag_eval_v3_hybrid_support as hs
from tests.str.rag_baseline_live_db import readonly_session
from tests.str.rag_baseline_support import cosine_summary
from tests.str.rag_eval_v3_hybrid_es import checked_keyword_search, es_count
from tests.str.rag_eval_v3_hybrid_run import (
    Prepared,
    prepare_query,
    search,
    sentence_hashes,
    snapshot_session,
)

REPO = guard.REPO_ROOT
CONSTANT_NAMES = ("RAG_CANDIDATES", "RAG_TOP_K", "MIN_SIMILARITY", "RAG_RRF_K", "RAG_MAX_QUERIES")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def refuse(
    settings: Settings,
    cand: dict,
    positions: dict,
    dry: bool,
    commit: str | None,
    *,
    check_result: bool = True,
) -> str | None:
    """① ~ ⑥ — 첫 거절 이유, 통과면 None. 임베딩·검색 전에(스냅샷 안에서 ②⑥ 을 한 번 더 — `evaluate`)."""
    if reason := hs.unconfirmed(cand):
        return f"v3 정답 확인 안 끝남: {reason}"
    if check_result and not dry and (reason := guard.result_problem(hs.RESULT_FILE)):
        return reason
    if reason := guard.criteria_problem(REPO, commit):
        return reason
    with readonly_session() as session:
        reason, db_rows = guard.db_problem(session, cand, positions)
    if reason:
        return reason
    return None if dry else guard.es_problem(settings.elastic_index, es_count(settings), db_rows)


def _top_record(top: list[tuple[str, float]], positions: dict[str, dict]) -> list[dict]:
    return [
        {
            "rank": i,
            "chunk_id": c,
            **{k: positions[c][k] for k in guard.POSITION_KEYS},
            "cosine": round(cos, 6),
        }
        for i, (c, cos) in enumerate(top, 1)
    ]


def run_condition(
    cond: hs.Condition, prepared: list[Prepared], positions: dict, cand: dict, session: Session
) -> dict:
    rows, ms, pg_ms = [], [], []
    for p in prepared:
        top, pg = search(p, cond, session)
        took = pg + (p.keyword_ms if cond.keyword and pg > 0 else 0.0)  # ES 는 질의마다 한 번 잰 값
        ms.append(took)
        pg_ms.append(pg)
        rows.append({"id": p.query["id"], "typology": p.query["typology"], "uses": p.query["uses"],
                     "search_ms": round(took, 1), "pg_fuse_ms": round(pg, 1),
                     "top10": _top_record(top, positions)})  # fmt: skip
    plain = [{"typology": r["typology"], "top10": [t["chunk_id"] for t in r["top10"]]} for r in rows]
    empty = [r for r in rows if "hit" not in r["uses"]]
    return {
        "name": cond.name, "filtered": cond.filtered, "kinds": list(cond.kinds), "keyword": cond.keyword,
        "metrics": hs.metrics(plain, hs.answer_sets(cand, filtered=cond.filtered)),
        "latency_ms": hs.latency([m for m in ms if m > 0]),  # 검색을 안 한 질의(유형 없음·필터 켬)는 뺌
        "pg_fuse_latency_ms": hs.latency([m for m in pg_ms if m > 0]),
        "no_answer": {r["id"]: (len(r["top10"]) if cond.filtered else
                                cosine_summary([t["cosine"] for t in r["top10"][: hs.TOP_HIT]])) for r in empty},
        "queries": rows,
    }  # fmt: skip


def configuration(settings: Settings, prepared: list[Prepared], dry: bool) -> dict:
    manifest = settings.corpus_dir / "manifest.json"
    return {
        "dry": dry, "criteria_commit": guard.CRITERIA_COMMIT, "head": guard.head_commit(REPO),
        "constants": {n: getattr(constants, n) for n in CONSTANT_NAMES},
        "embedding_model": settings.embedding_model, "elastic_index": settings.elastic_index,
        "retrieval_version": retrieval_version(settings),
        "manifest_sha256": _sha(manifest) if manifest.exists() else None,
        **{f"{p.stem}_sha256": _sha(p) for p in (hs.CANDIDATES_FILE, hs.QUERIES_FILE, hs.POSITIONS_FILE)},
        **sentence_hashes(prepared),
        "embedding_batches": sum(bool(p.embedding.queries) for p in prepared),
        "es_searches": sum(len(p.keyword_lists) for p in prepared),
        "keyword_ms_total": round(sum(p.keyword_ms for p in prepared), 1),
    }  # fmt: skip


def evaluate(settings: Settings, cand: dict, positions: dict, *, dry: bool) -> dict:
    keyword = None if dry else checked_keyword_search(settings)
    prepared = [prepare_query(q, settings, keyword, dry) for q in _load(hs.QUERIES_FILE)["queries"]]
    conds = hs.conditions()
    with snapshot_session() as session:  # 외부 호출 뒤 — 재확인과 9조건 검색이 같은 스냅샷(추가 검토 2)
        if reason := guard.db_problem(session, cand, positions)[0]:
            raise ValueError(f"스냅샷 재확인 실패: {reason}")
        runs = [run_condition(c, prepared, positions["positions"], cand, session) for c in conds]
    leaks = [r["name"] for r in runs if r["filtered"] and any(r["no_answer"].values())]
    verdict = (
        {"judged": False, "reason": f"필터 켬 정답 없는 질의가 0건이 아님: {leaks}"}
        if leaks
        else {"judged": True, **hs.verdict({c: r["metrics"] for c, r in zip(conds, runs, strict=True)})}
    )
    return {
        "_doc": "SCRUM-307 개발용 결정 — chunk_id·위치·cosine·지표만, 원문·검색어 문장 0 (docs/str/10 307 절).",
        "status": "done", "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "configuration": configuration(settings, prepared, dry),
        "embed_ms": {p.query["id"]: round(p.embed_ms, 1) for p in prepared},
        "verdict": verdict, "conditions": runs,
    }  # fmt: skip


def _write(path: Path, doc: dict, *, exclusive: bool) -> None:
    if leaks := hs.forbidden_keys(doc):
        raise ValueError(f"결과에 본문 키: {leaks[:3]}")
    with path.open("x" if exclusive else "w", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def main(argv: list[str] | None = None, *, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry", action="store_true", help="가짜 벡터 · ES 끔 · 경로 점검만")
    parser.add_argument("--criteria-commit", help="확인용 — 주면 고정한 기준 커밋과 같아야 함")
    args = parser.parse_args(argv)
    settings = settings or get_settings()
    if not hs.POSITIONS_FILE.exists():
        print(f"위치표가 없음({hs.POSITIONS_FILE.name}) — 호스트에서 rag_eval_v3_positions 를 먼저")
        return 2
    cand, positions = _load(hs.CANDIDATES_FILE), _load(hs.POSITIONS_FILE)
    if reason := refuse(settings, cand, positions, args.dry, args.criteria_commit):
        print(reason)
        return 2
    doc = evaluate(settings, cand, positions, dry=args.dry)
    _write(hs.DRY_RESULT_FILE if args.dry else hs.RESULT_FILE, doc, exclusive=not args.dry)
    print(json.dumps(doc["verdict"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
