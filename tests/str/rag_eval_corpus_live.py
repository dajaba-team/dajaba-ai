"""SCRUM-305 holdout_v2 실행·판정 (손 실행, pytest 수집 X — 진희 터미널. 하위 명령·순서는 docs/str/10 "305 실행 기록").

    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_eval_corpus_live <preflight|reserve|run|rejudge|check-restore>

reserve(예약 줄만) → 원장 커밋 → run(커밋된 예약·검색 표식 뒤 30개 검색 → 원장 값으로 판정 → chunk_id 만 결과 파일).
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import asdict
from hashlib import sha256

from sqlalchemy.orm import Session

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.embedding_client import make_embedding_client
from aml_ai.str.domain import constants
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str import rag_corpus_check as ck
from tests.str import rag_eval_corpus_gate as gate
from tests.str import rag_eval_corpus_ledger as cl
from tests.str.rag_eval_corpus_db import fan_counts as _fan_counts
from tests.str.rag_eval_corpus_db import read_corpus, read_tags, snapshot_session
from tests.str.rag_eval_corpus_db import snapshot_session as _snapshot_session
from tests.str.rag_eval_corpus_fan import dev_fan_facts as _dev_fan_facts
from tests.str.rag_eval_corpus_fan import dev_fan_grades as _dev_fan_grades
from tests.str.rag_eval_corpus_fan import fan_cases
from tests.str.rag_eval_corpus_guard import FAN_CASE_IDS, FanCase, Run
from tests.str.rag_eval_corpus_preflight import (
    fan_hit_at3,
    grade_table,
    grades_sha256,
    manifest_fan_problems,
    pre_run,
    preflight_problems,
    restore_problems,
    run_notes,
)
from tests.str.rag_eval_corpus_run import judge
from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR, FAN_BASELINE_HIT, query_text
from tests.str.rag_eval_v2_support import build_facts

EVAL_DIR = CORPUS_EVAL_DIR
GRADES_FILE = CORPUS_EVAL_DIR / "answers_corpus.json"  # 확인자 등급(청크 × 유형) — 시트 반영 때 생김
RESULT_FILE = CORPUS_EVAL_DIR / "result_holdout_v2.json"
DRAFT_FILE = CORPUS_EVAL_DIR / ck.DRAFT_NAME  # 태그 초벌 — 등급 파일의 draft_sha256 와 대조(⑭)


def _grades_doc() -> dict:
    return json.loads(GRADES_FILE.read_text(encoding="utf-8")) if GRADES_FILE.exists() else {}


def _applied_doc() -> dict:
    path = get_settings().corpus_dir / "pdf" / ck.APPLIED_NAME  # 공용 반영 표식(⑬)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _manifest() -> tuple[dict, str]:
    raw = (get_settings().corpus_dir / "manifest.json").read_bytes()
    return json.loads(raw), sha256(raw).hexdigest()


def preflight(out: Callable[[str], None] = print, session: Session | None = None) -> tuple:
    """(문제, PreRun, 유형별 태그 chunk_id, 검증한 등급표 스냅샷). 세션이 없으면 스냅샷 하나를 열어 모든 DB 읽기(⑮)."""
    with nullcontext(session) if session is not None else _snapshot_session() as s:
        (ids, fan, _), rows = read_tags(s), read_corpus(s)
    grades_doc = _grades_doc()
    manifest = _manifest()[0]
    problems = manifest_fan_problems(manifest)
    problems += preflight_problems(new_doc_fan=fan, tagged={t: len(v) for t, v in ids.items()})
    draft = DRAFT_FILE.read_bytes() if DRAFT_FILE.exists() else None  # 등급·표식·초벌·기대 코퍼스 전체(⑬·⑭·⑱)
    problems += ck.corpus_ready_problems(grades_doc=grades_doc, applied_doc=_applied_doc(), draft_raw=draft,
                                         manifest_documents=manifest.get("documents", []),
                                         old_rows=ck.load_old_rows(), rows=rows)  # fmt: skip
    pre = pre_run(ids, grades_doc)
    summary = {"tagged": dict(pre.tagged), "checked": dict(pre.checked), "problems": problems}
    out(json.dumps(summary, ensure_ascii=False))
    return problems, pre, ids, grades_doc


def _search(facts_list: list, session: Session | None = None) -> list[list[str]]:
    """원래 검색(유형 필터 → pgvector top-3, 빈칸 채우기 끔 — PG 만) — chunk_id 순서만. 세션을 주면 그 스냅샷에서."""
    embedder = make_embedding_client(get_settings())
    with nullcontext(session) if session is not None else snapshot_session() as s:
        return [[r.chunk_id for r in Retriever(s, embedder, enabled=True).retrieve(f)] for f in facts_list]


def reserve_cmd(out: Callable[[str], None] = print) -> int:
    """질의 스냅샷 대조 · preflight → 예약 줄만 쓰고 멈춤(검색 0). 다음은 원장 커밋 → run."""
    try:
        gate.queries_snapshot(EVAL_DIR)
    except ValueError as exc:
        out(str(exc))
        return 2
    problems, pre, _, snapshot = preflight(out)
    refused = "위 문제" if problems else cl.reserve(EVAL_DIR, pre.sha256(), grades_sha256(snapshot))
    if refused:
        out(f"예약 안 함: {refused}")
        return 2
    out(f"예약함 — 원장 파일({cl.LEDGER_NAME}) 하나만 커밋한 뒤 run")
    return 0


def run(out: Callable[[str], None] = print) -> int:
    try:
        queries = gate.queries_snapshot(EVAL_DIR)  # 304 고정 해시 — 예약·검색·판정은 이 스냅샷
    except ValueError as exc:
        out(str(exc))
        return 2
    with _snapshot_session() as session:  # 집계·검색 한 트랜잭션(REPEATABLE READ 읽기 전용, 추가 검토 4)
        problems, pre, ids, snapshot = preflight(out, session)
        refused = "위 문제 또는 결과 파일" if problems or RESULT_FILE.exists() else None
        refused = refused or gate.open_search_in(EVAL_DIR, pre.sha256(), grades_sha256(snapshot))
        if refused:
            out(f"검색 안 함: {refused}")
            return 2
        try:
            tops = _search([build_facts(q) for q in queries] + _dev_fan_facts(), session)
        except BaseException as exc:
            cl.record(EVAL_DIR, "aborted", reason=type(exc).__name__)
            raise
    try:
        if grades_sha256(_grades_doc()) != grades_sha256(snapshot):  # 검색 중 등급 파일 삭제·변경
            cl.record(EVAL_DIR, "aborted", reason="grades_changed")
            out("등급 파일이 예약 뒤 바뀜 — 판정 안 함(이 세트는 다시 못 돌림)")
            return 3
        manifest = [(q["id"], q["typology"], query_text(q)) for q in queries]
        runs = [Run(i, t, s, top) for (i, t, s), top in zip(manifest, tops[: len(queries)], strict=True)]
        fan = fan_cases(tops[len(queries) :])
        out_doc = {"verdict": judge(EVAL_DIR, runs, pre, snapshot, fan, queries),
                   "notes": run_notes(runs, ids, grade_table(snapshot), constants.RAG_TOP_K),
                   "runs": [asdict(r) for r in runs], "fan": [asdict(f) for f in fan]}  # fmt: skip
    except BaseException as exc:
        cl.record(EVAL_DIR, "aborted", reason=type(exc).__name__)
        raise
    RESULT_FILE.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cl.record(EVAL_DIR, "done")
    out(
        json.dumps(
            {k: out_doc["verdict"][k] for k in ("typology", "empty", "fan", "conclusion")}, ensure_ascii=False
        )
    )
    return 0


def rejudge(out: Callable[[str], None] = print) -> int:
    """결과 파일의 검색 결과로 다시 판정 — 원장 prior·예약 줄 등급표 해시. 거절이면 1."""
    doc = json.loads(RESULT_FILE.read_text(encoding="utf-8"))
    _, pre, _, grades_doc = preflight(out)
    try:
        verdict_out = judge(
            EVAL_DIR, [Run(**r) for r in doc["runs"]], pre, grades_doc, [FanCase(**f) for f in doc["fan"]]
        )
    except ValueError as exc:
        out(f"재판정 안 함: {exc}")
        return 1
    cl.record(EVAL_DIR, "done")
    out(json.dumps(verdict_out["typology"], ensure_ascii=False))
    return 0


def check_restore(out: Callable[[str], None] = print) -> int:
    """복원 뒤 — 425·태그 수·manifest + D07~D10 실제 검색(임베딩 호출) hit@3 1.0."""
    ids, _, total = read_tags()
    problems = restore_problems(total, {t: len(v) for t, v in ids.items()} | _fan_counts(), _manifest()[1])
    grades = _dev_fan_grades()
    try:
        hit = fan_hit_at3(_search(_dev_fan_facts()), [grades.get(i, {}) for i in FAN_CASE_IDS])
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 복원 확인 실패
        problems.append(f"D07~D10 검색 실패: {type(exc).__name__}")
    else:
        if hit < FAN_BASELINE_HIT:
            problems.append(f"FAN D07~D10 hit@3 {hit} < {FAN_BASELINE_HIT}")
    out(
        "\n".join(problems)
        if problems
        else "복원 확인 — 청크·태그 수·manifest·FAN D07~D10 hit@3 1.0 이 304 때와 같음"
    )
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cmd", choices=("preflight", "reserve", "run", "rejudge", "check-restore"))
    cmd = parser.parse_args(argv).cmd
    if cmd == "preflight":
        return 1 if preflight()[0] else 0
    return {"reserve": reserve_cmd, "run": run, "rejudge": rejudge, "check-restore": check_restore}[cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
