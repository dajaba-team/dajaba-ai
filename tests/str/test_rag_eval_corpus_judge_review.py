"""SCRUM-305 판정 묶음 — 추가 검토 4·5 회귀 (docs/str/10 "305 실행 기록"). DB·검색 0.

공용 값·픽스처는 `test_rag_eval_corpus_preflight` 에서 가져옴(파일 200줄 관문으로 나눔).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tests.str import rag_eval_corpus_ledger as cl
from tests.str import rag_eval_corpus_run as run_mod
from tests.str.rag_eval_corpus_preflight import grades_sha256
from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR
from tests.str.test_rag_eval_corpus_preflight import (
    GRADES_DOC,
    PRE,
    _fan,
    _reserve,
    _runs,
)


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    shutil.copy(CORPUS_EVAL_DIR / "queries_holdout.json", tmp_path / "queries_holdout.json")
    (tmp_path / cl.LEDGER_NAME).write_text("", encoding="utf-8")
    return tmp_path


# ───────── 추가 검토 4 — 판정이 고정 질의 목록만 받음 ─────────


def test_judge_rejects_queries_and_runs_missing_the_same_rows(eval_dir: Path) -> None:
    """질의·결과 양쪽에서 같은 CYCLE 실패 행 2개를 빼면(미달 → 통과로 바뀌는 길) 판정 줄 전에 거절."""
    from tests.str.rag_eval_corpus_support import load_queries

    _reserve(eval_dir)
    drop = {q["id"] for q in load_queries() if q["typology"] == "CYCLE"}
    drop = set(sorted(drop)[:2])
    queries = [q for q in load_queries() if q["id"] not in drop]
    runs = [r for r in _runs() if r.id not in drop]
    with pytest.raises(ValueError):
        run_mod.judge(eval_dir, runs, PRE, GRADES_DOC, _fan(), queries)
    assert cl.read_prior(eval_dir) == (None, None)


def test_judge_without_queries_reads_and_checks_eval_dir(eval_dir: Path) -> None:
    """queries 를 생략한 재판정 — eval_dir 의 질의 파일도 같은 대조(id 만 바꿔도 거절)."""
    _reserve(eval_dir)
    path = eval_dir / "queries_holdout.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["queries"][0]["id"] = "XX99"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        run_mod.judge(eval_dir, _runs(), PRE, GRADES_DOC, _fan())


@pytest.mark.parametrize("change", ["reduce", "reorder"])
def test_judge_with_fixed_queries_but_changed_eval_dir_writes_nothing(eval_dir: Path, change: str) -> None:
    """추가 검토 5 (2) — 고정 30개 queries 를 명시해도 eval_dir 이 축소·재정렬이면(그 세트 예약 줄이 있어도) 판정 줄 0."""
    from tests.str.rag_eval_corpus_support import load_queries

    path = eval_dir / "queries_holdout.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    if change == "reduce":
        drop = [q["id"] for q in doc["queries"] if q["typology"] == "CYCLE"][:2]
        doc["queries"] = [q for q in doc["queries"] if q["id"] not in drop]
    else:
        doc["queries"] = list(reversed(doc["queries"]))
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    line = {"set_sha256": cl.set_sha256(eval_dir), "status": "reserved", "pre_sha256": PRE.sha256(),
            "grades_sha256": grades_sha256(GRADES_DOC), "at": "t"}  # fmt: skip
    (eval_dir / cl.LEDGER_NAME).write_text(json.dumps(line) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        run_mod.judge(eval_dir, _runs(), PRE, GRADES_DOC, _fan(), load_queries())
    assert (eval_dir / cl.LEDGER_NAME).read_text(encoding="utf-8").count('"judged"') == 0
