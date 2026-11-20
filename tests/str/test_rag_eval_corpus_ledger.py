"""SCRUM-305 holdout_v2 원장 (docs/str/10 "305 실행 기록" 원장 표 ①~⑤ · 상태 전이). 임시 폴더만."""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

import pytest

from tests.str import rag_eval_corpus_ledger as cl
from tests.str.rag_eval_corpus_guard import PreRun, Prior
from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR

PRE = PreRun(
    tagged={"CYCLE": 12, "SCATTER_GATHER": 3, "GATHER_SCATTER": 15, "FX_RELAY": 0},
    checked={"CYCLE": True, "SCATTER_GATHER": True, "GATHER_SCATTER": True},
)
GRADES_SHA = "a" * 64
FIRST = Prior({"CYCLE": "pass", "SCATTER_GATHER": "not_judged", "GATHER_SCATTER": "fail"})
ALL_PASS = Prior({"CYCLE": "pass", "SCATTER_GATHER": "pass", "GATHER_SCATTER": "pass"})


@pytest.fixture
def eval_dir(tmp_path: Path) -> Path:
    shutil.copy(CORPUS_EVAL_DIR / "queries_holdout.json", tmp_path / "queries_holdout.json")
    (tmp_path / cl.LEDGER_NAME).write_text("", encoding="utf-8")
    return tmp_path


def _lines(eval_dir: Path) -> list[dict]:
    return [json.loads(x) for x in (eval_dir / cl.LEDGER_NAME).read_text(encoding="utf-8").splitlines()]


def _returns(prior: Prior, seen: list | None = None):  # noqa: ANN202
    def compute(pre_sha, grades_sha, last, last_sha):  # noqa: ANN001, ANN202
        if seen is not None:
            seen.append((pre_sha, grades_sha, last, last_sha))
        return {"typology": {t: {"status": s} for t, s in prior.statuses.items()}}, prior

    return compute


def test_reserve_writes_pre_and_grades_sha256(eval_dir: Path) -> None:
    assert cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA) is None
    (line,) = _lines(eval_dir)
    assert (line["status"], line["pre_sha256"], line["grades_sha256"]) == (
        "reserved",
        PRE.sha256(),
        GRADES_SHA,
    )
    assert cl.read_pre(eval_dir) == (PRE.sha256(), GRADES_SHA)


def test_same_set_reserved_twice_is_refused(eval_dir: Path) -> None:
    assert cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA) is None
    assert cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA) == cl.USED
    cl.record(eval_dir, "aborted", reason="KeyboardInterrupt")
    assert cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA) == cl.USED
    assert len(_lines(eval_dir)) == 2


@pytest.mark.parametrize("bad", ["", "abc", "Z" * 64])
def test_reserve_needs_sha256s(eval_dir: Path, bad: str) -> None:
    with pytest.raises(ValueError):
        cl.reserve(eval_dir, bad, GRADES_SHA)
    with pytest.raises(ValueError):
        cl.reserve(eval_dir, PRE.sha256(), bad)
    assert _lines(eval_dir) == []


def test_missing_ledger_is_refused_not_created(eval_dir: Path) -> None:
    (eval_dir / cl.LEDGER_NAME).unlink()
    assert cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA) == cl.MISSING
    assert not (eval_dir / cl.LEDGER_NAME).exists()


def test_judge_before_reserve_is_refused(eval_dir: Path) -> None:
    with pytest.raises(ValueError):
        cl.judge_locked(eval_dir, _returns(FIRST))


def test_compute_gets_ledger_values(eval_dir: Path) -> None:
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    seen: list = []
    cl.judge_locked(eval_dir, _returns(FIRST, seen))
    assert seen == [(PRE.sha256(), GRADES_SHA, None, None)]
    cl.record(eval_dir, "done")
    cl.judge_locked(eval_dir, _returns(FIRST, seen))
    assert seen[-1][2] == FIRST and seen[-1][3] == FIRST.sha256()


def test_first_verdict_only_right_after_reserve(eval_dir: Path) -> None:
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    cl.judge_locked(eval_dir, _returns(FIRST))
    with pytest.raises(ValueError):  # judged 바로 뒤 판정 — done 전 재판정·첫 판정 두 번
        cl.judge_locked(eval_dir, _returns(FIRST))


def test_rejudge_after_done_keeps_ledger_well_formed(eval_dir: Path) -> None:
    """추가 검토 1 ③ — 정상 run(reserved→judged→done) 뒤 rejudge(judged→done)도 형식 통과."""
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    cl.judge_locked(eval_dir, _returns(FIRST))
    cl.record(eval_dir, "done")
    cl.judge_locked(eval_dir, _returns(FIRST))
    cl.record(eval_dir, "done")
    assert [e["status"] for e in _lines(eval_dir)] == ["reserved", "judged", "done", "judged", "done"]
    assert cl.problems(eval_dir) == []


def test_judge_after_aborted_is_refused(eval_dir: Path) -> None:
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    cl.record(eval_dir, "aborted", reason="RuntimeError")
    with pytest.raises(ValueError):
        cl.judge_locked(eval_dir, _returns(FIRST))
    with pytest.raises(ValueError):
        cl.record(eval_dir, "done")
    assert [e["status"] for e in _lines(eval_dir)] == ["reserved", "aborted"]


def test_releasing_a_fail_is_refused(eval_dir: Path) -> None:
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    cl.judge_locked(eval_dir, _returns(FIRST))  # GATHER_SCATTER fail
    cl.record(eval_dir, "done")
    with pytest.raises(ValueError):
        cl.judge_locked(eval_dir, _returns(ALL_PASS))
    assert cl.read_prior(eval_dir)[0] == FIRST


def test_concurrent_rejudges_cannot_release_a_fail(eval_dir: Path) -> None:
    """추가 검토 1 ① — 두 재판정이 같은 prior(전부 pass)에서 출발: 하나가 fail 을 기록한 뒤 다른 하나의 pass 는 거절."""
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    cl.judge_locked(eval_dir, _returns(ALL_PASS))
    cl.record(eval_dir, "done")
    results: dict[str, object] = {}

    def slow_fail(*args):  # noqa: ANN002, ANN202
        time.sleep(0.2)
        return _returns(FIRST)(*args)

    def run(name: str, compute) -> None:  # noqa: ANN001
        try:
            cl.judge_locked(eval_dir, compute)
            cl.record(eval_dir, "done")
            results[name] = "ok"
        except ValueError as exc:
            results[name] = str(exc)

    a = threading.Thread(target=run, args=("fail", slow_fail))
    b = threading.Thread(target=run, args=("pass", _returns(ALL_PASS)))
    a.start()
    time.sleep(0.05)
    b.start()
    a.join()
    b.join()
    assert results["fail"] == "ok" and results["pass"] != "ok"
    assert cl.read_prior(eval_dir)[0] == FIRST
    assert cl.problems(eval_dir) == []


def test_tampered_prior_line_is_rejected(eval_dir: Path) -> None:
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    cl.judge_locked(eval_dir, _returns(FIRST))
    lines = _lines(eval_dir)
    lines[-1]["prior"]["GATHER_SCATTER"] = "pass"
    (eval_dir / cl.LEDGER_NAME).write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    with pytest.raises(ValueError):
        cl.read_prior(eval_dir)
    assert cl.problems(eval_dir)


def test_problems_catch_stale_prior_and_release(eval_dir: Path) -> None:
    """손으로 덧붙인 줄 — 계산에 쓴 prior 가 최신이 아니거나 fail 을 푼 판정 줄."""
    cl.reserve(eval_dir, PRE.sha256(), GRADES_SHA)
    cl.judge_locked(eval_dir, _returns(FIRST))
    cl.record(eval_dir, "done")
    line = {"set_sha256": cl.set_sha256(eval_dir), "status": "judged", "prior": dict(ALL_PASS.statuses),
            "prior_sha256": ALL_PASS.sha256(), "from_prior_sha256": None, "at": "t"}  # fmt: skip
    with (eval_dir / cl.LEDGER_NAME).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line) + "\n")
    probs = cl.problems(eval_dir)
    assert any("최신" in p for p in probs) and any("미달" in p for p in probs)


def test_problems_catch_bad_lines(eval_dir: Path) -> None:
    path = eval_dir / cl.LEDGER_NAME
    path.write_text('{"status": "judged", "set_sha256": "x", "at": "t"}\nnot json\n', encoding="utf-8")
    probs = cl.problems(eval_dir)
    assert any("JSON" in p for p in probs) and any("전이" in p for p in probs)


def test_repo_ledger_is_well_formed() -> None:
    assert (CORPUS_EVAL_DIR / cl.LEDGER_NAME).is_file()
    assert cl.problems(CORPUS_EVAL_DIR) == []
