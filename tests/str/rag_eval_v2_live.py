"""SCRUM-275 평가 실행·판정 (손 실행, pytest 수집 X — 진희 터미널. docs/str/10 "판정 기준").

ES 는 호스트 포트가 없어 AI 컨테이너 안에서 — 실행 명령은 docs/str/10 "도구"(tests·tools 읽기 전용 마운트,
결과 폴더 `tests/str/rag_eval_v2` 만 쓰기 마운트).

질의마다 지금 경로(빈칸 채우기 끔)와 켬을 실제 임베딩·PG·ES 로 돌려 chunk_id·시간만 남김(본문 0).
개발용은 여러 번 가능(검색어 실험). 보류용은 **한 번만** — 검색 전에 git 추적 원장(`rag_eval_v2_ledger`)에
세트 해시를 예약하고, 이미 있으면(끝났든 중단됐든, 결과 파일을 지웠든) 거절. 중간 실패도 결과 파일·원장에 남음. 정답 확인이 안 끝났거나
개발용 결과가 없어도 거절. 보류용 판정 = 개발용 + 보류용 실행 결과로 `verdict`(②③ 은 30개 전부).
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.db import get_engine
from aml_ai.shared.infrastructure.embedding_client import make_embedding_client
from aml_ai.str.domain import constants
from aml_ai.str.infrastructure.keyword_search import make_keyword_search
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str import rag_eval_v2_ledger as ledger
from tests.str.rag_eval_v2_support import (
    EVAL_DIR,
    QueryRun,
    build_facts,
    grade_lookup,
    load_queries,
    unchecked,
    verdict,
)

_MS = 1000


def result_path(split: str) -> Path:
    return EVAL_DIR / f"result_{split}.json"


def refuse_reason(split: str, use_keyword: bool) -> str | None:
    if split != "holdout":
        return None
    if result_path("holdout").exists():
        return "보류용 결과가 이미 있음 — 한 번만 판정"
    if not result_path("dev").exists():
        return "개발용 결과가 없음 — 개발용을 먼저 돌림(②③ 은 30개 전부)"
    dev = json.loads(result_path("dev").read_text(encoding="utf-8"))
    if dev.get("status") != "done":
        return "개발용 결과가 끝난 상태가 아님 — 개발용을 다시 돌림"
    if dev.get("keyword") != use_keyword:
        return "개발용 마지막 결과와 키워드 설정이 다름 — 고른 설정으로 개발용을 다시 돌린 뒤"
    answers = EVAL_DIR / "answers_holdout.json"
    if not answers.exists() or unchecked(json.loads(answers.read_text(encoding="utf-8"))):
        return "보류용 정답 확인이 안 끝남(checked_by·checked_at)"
    return None


def reserve_holdout() -> str | None:
    """원장에 예약(검색 전) — 통과면 None, 아니면 거절 이유. 결과 파일은 예약 기록이 아님."""
    return ledger.reserve(EVAL_DIR)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write(split: str, doc: dict) -> None:
    result_path(split).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_query(
    settings: Settings, query: dict, grades: dict[str, int], use_keyword: bool
) -> tuple[QueryRun, dict]:
    facts = build_facts(query)
    embedder = make_embedding_client(settings)
    with Session(get_engine()) as session:
        started = time.perf_counter()
        first = Retriever(session, embedder, enabled=True).retrieve(facts)
        ms_off = (time.perf_counter() - started) * _MS
        session.commit()
        keyword = make_keyword_search(settings) if use_keyword else None
        started = time.perf_counter()
        on = Retriever(
            session,
            embedder,
            enabled=True,
            gap_fill=True,
            keyword=keyword,
            release=session.commit,
            fill_session=lambda: Session(get_engine()),
        ).retrieve(facts)  # fmt: skip — 초안과 같은 격리
        ms_on = (time.perf_counter() - started) * _MS
    first_ids, on_ids = [r.chunk_id for r in first], [r.chunk_id for r in on]
    filled = [] if query["expect_empty"] else [grades.get(c, 0) for c in on_ids[len(first_ids) :]]
    run = QueryRun(
        query["id"], query["split"], query["typology"], query["expect_empty"], first_ids, on_ids, filled
    )
    scores = [round(r.score, 4) for r in on[len(first) :]]
    return run, {"ms_off": round(ms_off), "ms_on": round(ms_on), "filled_cosine": scores}


def evaluate(split: str, use_keyword: bool, settings: Settings, done: list[str]) -> dict:
    answers_file = EVAL_DIR / f"answers_{split}.json"
    answers = (
        json.loads(answers_file.read_text(encoding="utf-8")) if answers_file.exists() else {"queries": []}
    )
    lookup = grade_lookup(answers)
    rows = []
    for q in load_queries(split):
        rows.append(run_query(settings, q, lookup.get(q["id"], {}), use_keyword))
        done.append(q["id"])
    out = {
        "split": split,
        "status": "done",
        "finished_at": _now(),
        "keyword": use_keyword,
        "elastic_index": settings.elastic_index,
        "embedding_model": settings.embedding_model,
        "constants": {
            n: getattr(constants, n) for n in ("RAG_TOP_K", "RAG_CANDIDATES", "MIN_SIMILARITY", "RAG_RRF_K")
        },
        "answers_unchecked": unchecked(answers) if answers["queries"] else "answers_missing",
        "runs": [{**asdict(run), **extra} for run, extra in rows],
    }
    if split == "holdout":
        dev = json.loads(result_path("dev").read_text(encoding="utf-8"))
        dev_runs = [QueryRun(**{k: r[k] for k in QueryRun.__dataclass_fields__}) for r in dev["runs"]]
        out["verdict"] = verdict(dev_runs + [run for run, _ in rows])
    return out


def main(argv: list[str] | None = None, *, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "holdout"), required=True)
    parser.add_argument("--no-keyword", action="store_true", help="ES 없이 벡터만(비교용)")
    args = parser.parse_args(argv)
    use_keyword = not args.no_keyword
    reason = refuse_reason(args.split, use_keyword)
    if reason is None and args.split == "holdout":
        reason = reserve_holdout()
    if reason:
        print(reason)
        return 2
    done: list[str] = []
    try:
        out = evaluate(args.split, use_keyword, settings or get_settings(), done)
    except BaseException as exc:
        if args.split == "holdout":  # 보류용은 중단돼도 기록을 남김 — 다시 못 돌림. 개발용은 지난 결과를 지킴
            _write("holdout", {"split": "holdout", "status": "aborted", "aborted_at": _now(),
                               "reason": type(exc).__name__, "queries_run": done, "keyword": use_keyword})  # fmt: skip
            ledger.record(EVAL_DIR, "aborted", reason=type(exc).__name__, queries_run=len(done))
        raise
    _write(args.split, out)
    if args.split == "holdout":
        ledger.record(EVAL_DIR, "done")
    print(
        json.dumps(
            out.get("verdict", {"filled": sum(len(r["grades"]) for r in out["runs"])}), ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
