"""SCRUM-308 ① 컷오프 실행 전 거절 (추가 검토 1) — 고정 기준 커밋 · 입력 바이트 = 기준 커밋 · 구조 · 결과 파일 0."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.str import rag_eval_v3_cutoff as cut
from tests.str import rag_eval_v3_cutoff_guard as guard

SECTION = f"{guard.CRITERIA_HEADING}, 2026-11-21)\n\n규칙\n"
MD = f"# 10\n\n{SECTION}\n## 버전\n"
QUERIES = {
    "queries": [
        {"id": "FI01", "uses": ["hit"]},
        {"id": "SG05", "uses": ["hit"]},
        {"id": "FX01", "uses": ["empty"]},
    ]
}


def _rows(off: bool) -> list[dict]:
    a = {"chunk_id": "a1", "cosine": 0.5}
    return [{"id": "FI01", "typology": "FAN_IN", "uses": ["hit"], "top10": [a]},
            {"id": "SG05", "typology": "SCATTER_GATHER", "uses": ["hit"], "top10": [{"chunk_id": "s", "cosine": 0.29}]},
            {"id": "FX01", "typology": "FX_RELAY", "uses": ["empty"], "top10": [{"chunk_id": "n", "cosine": 0.4}] if off else []}]  # fmt: skip


RESULT = {"conditions": [{"name": guard.DRAFT_CONDITION, "filtered": True, "queries": _rows(False)}]
          + [{"name": f"off_{i}", "filtered": False, "queries": _rows(True)} for i in range(6)]}  # fmt: skip
CAND = {"candidates": {"FAN_IN": [{"chunk_id": "a1", "grade": 2, "db_tagged": True}]}}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _write(repo: Path, md: str, result: dict) -> None:
    for path, body in ((guard.DOC_10, md), (guard.RESULT_307, json.dumps(result)),
                       (guard.CANDIDATES, json.dumps(CAND)), (guard.QUERIES, json.dumps(QUERIES))):  # fmt: skip
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(body, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _git(tmp_path, "init", "-q")
    _write(tmp_path, MD, RESULT)
    monkeypatch.setattr(guard, "CRITERIA_COMMIT", _commit(tmp_path, "criteria"))
    return tmp_path


def test_clean_repo_passes_and_writes_once(repo: Path) -> None:
    assert guard.criteria_problem(repo) is None
    out = repo / "result_308_cutoff.json"
    assert cut.main(repo, out) == 0 and json.loads(out.read_text())["verdict"]["judged"] is True
    assert cut.main(repo, out) == 2  # 덮어쓰기 금지


def test_criteria_changed_and_committed_is_refused(repo: Path) -> None:
    _write(repo, MD.replace("규칙", "고친 규칙"), RESULT)
    _commit(repo, "edit rule")
    assert "바뀌어 커밋됨(HEAD)" in guard.criteria_problem(repo)


def test_criteria_changed_in_worktree_or_not_ancestor(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / guard.DOC_10).write_text(MD.replace("규칙", "고친 규칙"), encoding="utf-8")
    assert "바뀜(작업 트리)" in guard.criteria_problem(repo)
    monkeypatch.setattr(guard, "CRITERIA_COMMIT", "0" * 40)
    assert "리포에 없음" in guard.criteria_problem(repo)


def test_sg05_uses_dropped_input_is_refused_without_file(repo: Path) -> None:
    """추가 검토 1 — SG05 `uses` 를 비우면 정답 있는 질의가 정답 없는 질의로 섞여 채택이 뒤집힘 → 바이트 대조로 거절."""
    tampered = json.loads(json.dumps(RESULT))
    tampered["conditions"][0]["queries"][1]["uses"] = []
    (repo / guard.RESULT_307).write_text(json.dumps(tampered), encoding="utf-8")
    assert guard.read_inputs(repo)[2] == "입력이 기준 커밋과 다름(result_307.json)"
    out = repo / "result_308_cutoff.json"
    assert cut.main(repo, out) == 2 and not out.exists()


def test_structure_problems() -> None:
    no_off = {"conditions": RESULT["conditions"][:1]}
    assert guard.structure_problem(no_off, QUERIES) == "필터 끔 조건 수 0 ≠ 6"
    bad = json.loads(json.dumps(RESULT))
    bad["conditions"][3]["queries"][1]["uses"] = []
    assert guard.structure_problem(bad, QUERIES) == "질의 id·uses 가 v3 질의와 다름(off_2)"
    assert guard.structure_problem(RESULT, QUERIES) is None


def test_structure_problem_blocks_committed_bad_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _git(tmp_path, "init", "-q")
    _write(tmp_path, MD, {"conditions": RESULT["conditions"][:1]})  # 기준 커밋 자체에 필터 끔 조건이 없음
    monkeypatch.setattr(guard, "CRITERIA_COMMIT", _commit(tmp_path, "criteria"))
    out = tmp_path / "result_308_cutoff.json"
    assert cut.main(tmp_path, out) == 2 and not out.exists()


def test_fixed_criteria_commit_is_the_pre_result_commit() -> None:
    assert guard.CRITERIA_COMMIT == "87aef099a91be90440d79b65f0daff462aa73216"
