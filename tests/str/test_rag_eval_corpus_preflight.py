"""SCRUM-305 실행 전 점검·복원 확인·판정 묶음 (docs/str/10 "305 실행 기록"). DB·검색 0 — 합성 입력만."""

from __future__ import annotations

import inspect
import json
import shutil
from pathlib import Path

import pytest

from tests.str import rag_eval_corpus_ledger as cl
from tests.str import rag_eval_corpus_run as run_mod
from tests.str.rag_eval_corpus_guard import FAN_CASE_IDS, FanCase, PreRun, Run
from tests.str.rag_eval_corpus_preflight import (
    BASELINE_CHUNKS,
    BASELINE_MANIFEST_SHA256,
    BASELINE_TAGGED,
    NEW_DOC_IDS,
    grade0_ratio,
    grades_sha256,
    manifest_fan_problems,
    pre_run,
    preflight_problems,
    restore_problems,
    top3_jaccard,
)
from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR, query_manifest

REPO_MANIFEST = json.loads(
    (Path(__file__).parents[2] / "corpus" / "manifest.json").read_text(encoding="utf-8")
)


def _doc(doc_id: str, **tags) -> dict:
    return {"id": doc_id, "typologies": [], **tags}


# ───────── ① 새 문서 FAN 태그 0 ─────────


def test_repo_manifest_new_docs_have_no_fan_tags() -> None:
    assert manifest_fan_problems(REPO_MANIFEST) == []


@pytest.mark.parametrize(
    "doc",
    [
        _doc(NEW_DOC_IDS[0], typologies=["FAN_IN"]),
        _doc(NEW_DOC_IDS[1], typology_pages={"CYCLE": [2], "FAN_OUT": [3]}),
        _doc(NEW_DOC_IDS[2], typology_pages={"fan_in": [5]}),
    ],
    ids=["typologies", "pages", "lowercase"],
)
def test_fan_tag_on_new_doc_is_a_problem(doc: dict) -> None:
    assert manifest_fan_problems({"documents": [doc]}) != []


def test_fan_tag_on_old_doc_and_other_tags_on_new_doc_are_fine() -> None:
    docs = [
        _doc("fincen-funnel-2014", typologies=["FAN_IN"]),
        _doc(NEW_DOC_IDS[2], typology_pages={"CYCLE": [9]}),
    ]
    assert manifest_fan_problems({"documents": docs}) == []


def test_db_fan_tags_on_new_docs_block_the_run() -> None:
    counts = {"CYCLE": 12, "SCATTER_GATHER": 10, "GATHER_SCATTER": 11, "FX_RELAY": 0}
    assert preflight_problems(new_doc_fan=0, tagged=counts) == []
    assert preflight_problems(new_doc_fan=1, tagged=counts) != []


# ───────── 실행 전 고정값 ─────────

GRADES_DOC = {
    "checked_by": "확인자",
    "checked_at": "2026-11-22",
    "grades": {
        "CYCLE": [{"chunk_id": "c1", "grade": 1}, {"chunk_id": "c2", "grade": 0}],
        "GATHER_SCATTER": [],
    },
}


def test_pre_run_checked_only_when_every_tagged_chunk_is_graded() -> None:
    tagged_ids = {"CYCLE": ["c1", "c2"], "SCATTER_GATHER": [], "GATHER_SCATTER": ["g1"], "FX_RELAY": []}
    pre = pre_run(tagged_ids, GRADES_DOC)
    assert dict(pre.tagged) == {"CYCLE": 2, "SCATTER_GATHER": 0, "GATHER_SCATTER": 1, "FX_RELAY": 0}
    assert dict(pre.checked) == {"CYCLE": True, "SCATTER_GATHER": True, "GATHER_SCATTER": False}


def test_pre_run_without_checker_name_is_not_checked() -> None:
    tagged_ids = {"CYCLE": ["c1", "c2"], "SCATTER_GATHER": [], "GATHER_SCATTER": [], "FX_RELAY": []}
    pre = pre_run(tagged_ids, {**GRADES_DOC, "checked_by": ""})
    assert not any(pre.checked.values())


# ───────── 복원 확인 ─────────


def test_restore_baseline_passes() -> None:
    assert restore_problems(BASELINE_CHUNKS, dict(BASELINE_TAGGED), BASELINE_MANIFEST_SHA256) == []
    assert BASELINE_MANIFEST_SHA256.startswith("02bcd88b")  # 304 때 manifest(retrieval_version @02bcd88b)


@pytest.mark.parametrize(
    "chunks, tag_delta, sha",
    [(722, {}, None), (BASELINE_CHUNKS, {"CYCLE": 9}, None), (BASELINE_CHUNKS, {}, "0" * 64)],
    ids=["chunks", "tags", "manifest"],
)
def test_restore_mismatch_is_reported(chunks: int, tag_delta: dict, sha: str | None) -> None:
    tagged = {**BASELINE_TAGGED, **tag_delta}
    assert restore_problems(chunks, tagged, sha or BASELINE_MANIFEST_SHA256) != []


# ───────── 판정 — pre·prior 는 원장 값만 ─────────

PRE = PreRun(
    tagged={"CYCLE": 12, "SCATTER_GATHER": 3, "GATHER_SCATTER": 15, "FX_RELAY": 0},
    checked={"CYCLE": True, "SCATTER_GATHER": True, "GATHER_SCATTER": True},
)


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    shutil.copy(CORPUS_EVAL_DIR / "queries_holdout.json", tmp_path / "queries_holdout.json")
    (tmp_path / cl.LEDGER_NAME).write_text("", encoding="utf-8")
    return tmp_path


def _runs() -> list[Run]:
    return [Run(i, t, text, []) for i, t, text in query_manifest()]


def _fan() -> list[FanCase]:
    return [FanCase(i, ["a"], ["a"], {"a": 1}) for i in FAN_CASE_IDS]


def test_judge_takes_no_hash_or_prior_from_caller() -> None:
    params = set(inspect.signature(run_mod.judge).parameters)
    assert not params & {"pre_sha256", "prior", "prior_sha256"}


def _reserve(eval_dir: Path, doc: dict = GRADES_DOC) -> None:
    assert cl.reserve(eval_dir, PRE.sha256(), grades_sha256(doc)) is None


def test_judge_rejects_pre_run_different_from_reserved(eval_dir: Path) -> None:
    _reserve(eval_dir)
    other = PreRun(tagged={**PRE.tagged, "CYCLE": 99}, checked=dict(PRE.checked))
    with pytest.raises(ValueError):
        run_mod.judge(eval_dir, _runs(), other, GRADES_DOC, _fan())
    assert [e["status"] for e in map(json.loads, (eval_dir / cl.LEDGER_NAME).read_text().splitlines())] == [
        "reserved"
    ]


def test_judge_rejects_grades_snapshot_different_from_reserved(eval_dir: Path) -> None:
    """추가 검토 1 ② — 예약 때 고정한 등급표와 다른 등급표(삭제·변경)로는 판정 안 함."""
    _reserve(eval_dir)
    for doc in ({}, {**GRADES_DOC, "grades": {"CYCLE": [{"chunk_id": "c1", "grade": 2}]}}):
        with pytest.raises(ValueError):
            run_mod.judge(eval_dir, _runs(), PRE, doc, _fan())
    assert cl.read_prior(eval_dir) == (None, None)


def test_judge_first_then_rejudge_uses_ledger_prior(eval_dir: Path) -> None:
    _reserve(eval_dir)
    first = run_mod.judge(eval_dir, _runs(), PRE, GRADES_DOC, _fan())
    assert first["typology"]["CYCLE"]["status"] == "fail"  # 결과 0건 — 미달
    cl.record(eval_dir, "done")
    again = run_mod.judge(eval_dir, _runs(), PRE, GRADES_DOC, _fan())
    assert again["typology"]["CYCLE"]["reason"] == "pinned"  # 원장 prior 의 미달 고정
    assert [e["status"] for e in map(json.loads, (eval_dir / cl.LEDGER_NAME).read_text().splitlines())] == [
        "reserved",
        "judged",
        "done",
        "judged",
    ]


def test_judge_without_reservation_is_refused(eval_dir: Path) -> None:
    with pytest.raises(ValueError):
        run_mod.judge(eval_dir, _runs(), PRE, GRADES_DOC, _fan())


# ───────── 참고 기록 ─────────


def test_top3_jaccard_per_typology() -> None:
    runs = [Run("a", "CYCLE", "x", ["1", "2", "3"]), Run("b", "CYCLE", "y", ["1", "2", "4"])]
    assert top3_jaccard(runs) == {"CYCLE": 0.5}


def test_grade0_ratio_of_tagged_chunks() -> None:
    tagged_ids = {"CYCLE": ["c1", "c2", "c3", "c4"]}
    grades = {("CYCLE", "c1"): 1, ("CYCLE", "c2"): 0}
    assert grade0_ratio(tagged_ids, grades) == {"CYCLE": 0.75}  # 없는 등급 = 0
