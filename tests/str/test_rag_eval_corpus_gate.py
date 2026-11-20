"""SCRUM-305 holdout_v2 검색 시작 문 (docs/str/10 "305 실행 기록" — 추가 검토 3). 임시 git 리포만, DB·검색 0."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.str import rag_eval_corpus_gate as gate
from tests.str import rag_eval_corpus_ledger as cl
from tests.str.rag_eval_corpus_guard import normalized_sha256
from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR
from tests.str.test_rag_eval_corpus_set import QUERIES_SHA256

PRE, GRADES = "b" * 64, "c" * 64
REL = Path("tests/str/rag_eval_corpus")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    eval_dir = root / REL
    eval_dir.mkdir(parents=True)
    shutil.copy(CORPUS_EVAL_DIR / "queries_holdout.json", eval_dir / "queries_holdout.json")
    (eval_dir / cl.LEDGER_NAME).write_text("", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    return root


def _commit(root: Path) -> None:
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "reserve")


def test_fixed_queries_hash_matches_304() -> None:
    assert gate.QUERIES_SHA256 == QUERIES_SHA256


def test_snapshot_refuses_id_only_change(repo: Path) -> None:
    path = repo / REL / "queries_holdout.json"
    assert normalized_sha256(gate.queries_snapshot(repo / REL)) == QUERIES_SHA256
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["queries"][0]["id"] = "XX99"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        gate.queries_snapshot(repo / REL)


def test_reserved_but_not_committed_is_refused(repo: Path) -> None:
    cl.reserve(repo / REL, PRE, GRADES)
    assert gate.open_search(repo, REL, PRE, GRADES) == gate.NOT_COMMITTED


def test_committed_reservation_opens_once(repo: Path) -> None:
    cl.reserve(repo / REL, PRE, GRADES)
    _commit(repo)
    assert gate.open_search(repo, REL, PRE, GRADES) is None
    assert gate.open_search(repo, REL, PRE, GRADES) == gate.ALREADY_SEARCHED  # 같은 작업 트리 다시


def test_values_must_match_the_committed_reservation(repo: Path) -> None:
    cl.reserve(repo / REL, PRE, GRADES)
    _commit(repo)
    assert gate.open_search(repo, REL, PRE, "d" * 64) == gate.MISMATCH
    assert gate.open_search(repo, REL, PRE, GRADES) is None  # 거절은 표식을 안 남김


def test_empty_ledger_restore_is_refused(repo: Path) -> None:
    cl.reserve(repo / REL, PRE, GRADES)
    _commit(repo)
    (repo / REL / cl.LEDGER_NAME).write_text("", encoding="utf-8")  # 빈 원장 복원
    assert gate.open_search(repo, REL, PRE, GRADES) == gate.NOT_RESERVED_HERE


def test_aborted_then_new_worktree_is_refused(repo: Path, tmp_path: Path) -> None:
    """첫 검색이 중단된 뒤 HEAD 에서 새 작업 트리를 만들어도(원장엔 예약 한 줄뿐) 공유 ref 표식으로 거절."""
    cl.reserve(repo / REL, PRE, GRADES)
    _commit(repo)
    assert gate.open_search(repo, REL, PRE, GRADES) is None
    cl.record(repo / REL, "aborted", reason="KeyboardInterrupt")
    wt = tmp_path / "wt"
    _git(repo, "worktree", "add", "-q", str(wt), "HEAD")
    assert (wt / REL / cl.LEDGER_NAME).read_text(encoding="utf-8").count('"reserved"') == 1
    assert gate.open_search(wt, REL, PRE, GRADES) == gate.ALREADY_SEARCHED


def test_local_aborted_is_refused(repo: Path) -> None:
    cl.reserve(repo / REL, PRE, GRADES)
    _commit(repo)
    cl.record(repo / REL, "aborted", reason="x")
    assert gate.open_search(repo, REL, PRE, GRADES) == gate.NOT_RESERVED_HERE
