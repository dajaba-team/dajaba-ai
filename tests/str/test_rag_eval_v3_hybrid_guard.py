"""SCRUM-307 실행 전 거절 ①~⑥ · 결과 기록에 본문 키 없음 (docs/str/10 307 실행 절)."""

from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import pytest

from aml_ai.str.domain.rag_queries import SearchQuery
from tests.str import rag_eval_v3_hybrid_guard as guard
from tests.str import rag_eval_v3_hybrid_live as live
from tests.str import rag_eval_v3_hybrid_support as hs
from tests.str.rag_baseline_live_run import PreparedEmbedding
from tests.str.rag_eval_v3_hybrid_run import Prepared

SECTION = f"{hs.CRITERIA_HEADING}, 2026-11-21)\n\n규칙 ≥ 0.10\n"
LINE_09 = f"{hs.CRITERIA_09_PREFIX} — 결과 보기 전) | 결정 | 이유 | 버린 대안 |\n"


def _run(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, ten: str, nine: str, message: str) -> str:
    (repo / "docs/str").mkdir(parents=True, exist_ok=True)
    (repo / guard.DOC_10).write_text(ten, encoding="utf-8")
    (repo / guard.DOC_09).write_text(nine, encoding="utf-8")
    _run(repo, "add", "-A")
    _run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)
    return _run(repo, "rev-parse", "HEAD")


def _crit(monkeypatch: pytest.MonkeyPatch, repo: Path, given: str | None, fixed: str) -> str | None:
    """고정 기준 커밋은 인자로 못 바꿈 — 테스트만 모듈 상수를 바꿔 끼움(추가 검토 2)."""
    monkeypatch.setattr(guard, "CRITERIA_COMMIT", fixed)
    return guard.criteria_problem(repo, given)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _run(tmp_path, "init", "-q")
    return tmp_path


def test_criteria_fixed_commit_ancestor_and_unchanged_passes(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    criteria = _commit(repo, f"# 10\n\n{SECTION}\n## 버전\n", LINE_09, "criteria")
    _commit(repo, f"# 10\n\n{SECTION}\n## 버전\n하네스 뒤\n", LINE_09 + "| 다른 줄 |\n", "harness")
    assert _crit(monkeypatch, repo, None, criteria) is None
    assert _crit(monkeypatch, repo, criteria, criteria) is None


def test_criteria_other_commit_given_is_refused(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    criteria = _commit(repo, SECTION, LINE_09, "criteria")
    edited = _commit(repo, SECTION.replace("0.10", "0.05"), LINE_09, "edit rule")
    # 추가 검토 1 — 기준을 고친 커밋 자체·HEAD 를 넘겨도 고정 커밋으로만 봄
    for given in (edited, "HEAD", criteria[:7]):
        assert "고정한 기준 커밋과 다름" in _crit(monkeypatch, repo, given, criteria)
    assert "바뀜(docs/str/10_rag.md)" in _crit(monkeypatch, repo, None, criteria)


def test_criteria_fixed_missing_or_not_ancestor(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = _commit(repo, "# 10\n", "", "before")
    assert "리포에 없음" in _crit(monkeypatch, repo, None, "0" * 40)
    assert "307 기준이 없음" in _crit(monkeypatch, repo, None, first)
    _run(repo, "checkout", "-qb", "side")
    side = _commit(repo, SECTION, LINE_09, "side")
    _run(repo, "checkout", "-q", "-")
    assert "HEAD 조상에 없음" in _crit(monkeypatch, repo, None, side)


def test_fixed_criteria_commit_is_the_pre_result_commit() -> None:
    assert guard.CRITERIA_COMMIT == "48b76ad0609728d87ded41a82b6133ab660eda2c"
    assert list(inspect.signature(guard.criteria_problem).parameters) == [
        "repo",
        "given",
    ]  # fixed 주입 길 없음


def test_es_index_and_count() -> None:
    assert guard.es_problem(hs.ES_INDEX, 722, 722) is None
    assert "가 아님" in guard.es_problem("ai_reference_chunks_v1", 722, 722)
    assert "425 ≠ DB 행 수 722" in guard.es_problem(hs.ES_INDEX, 425, 722)


def test_positions_and_result_exists(tmp_path: Path) -> None:
    ok = {"doc_id": "d", "page": 1, "pos": 1}
    assert guard.positions_problem({"a": ok, "b": ok}, {"a", "b"}) is None
    assert guard.positions_problem({"a": ok, "x": ok}, {"a", "b"}) == "위치표 ≠ DB(빠짐 1 · 더 있음 1)"
    for bad in (
        {**ok, "excerpt": "본문"},
        {**ok, "chunk_id": "z"},
        {**ok, "page": True},
        {"doc_id": "d", "page": 1},
    ):
        assert guard.positions_problem({"a": ok, "b": bad}, {"a", "b"}) == "위치표 행 형식이 다름 1"
    out = tmp_path / "result_307.json"
    assert guard.result_problem(out) is None
    out.write_text("{}", encoding="utf-8")
    assert "이미 있음" in guard.result_problem(out)


def test_write_is_exclusive_and_rejects_body_keys(tmp_path: Path) -> None:
    out = tmp_path / "r.json"
    live._write(out, {"ok": 1}, exclusive=True)
    with pytest.raises(FileExistsError):
        live._write(out, {"ok": 2}, exclusive=True)
    with pytest.raises(ValueError, match="본문 키"):
        live._write(tmp_path / "s.json", {"conditions": [{"text": "x"}]}, exclusive=True)
    assert not (tmp_path / "s.json").exists()


def test_condition_record_has_no_body_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    query = {"id": "FI01", "typology": "FAN_IN", "uses": ["hit"]}
    empty = {"id": "FX01", "typology": "FX_RELAY", "uses": ["empty"]}
    emb = PreparedEmbedding([SearchQuery("a", "en", "sentence")], [[0.0]], "m")
    prepared = [Prepared(query, emb), Prepared(empty, emb)]
    positions = {"x": {"doc_id": "d", "page": 1, "pos": 1}}
    monkeypatch.setattr(live, "search", lambda p, c, s: ([("x", 0.5)] if p.query is query else [], 1.0))
    cand = {"candidates": {"FAN_IN": [{"chunk_id": "x", "grade": 2, "db_tagged": True}]}}
    rec = live.run_condition(hs.conditions()[0], prepared, positions, cand, None)
    assert hs.forbidden_keys(rec) == []
    assert rec["queries"][0]["top10"] == [{"rank": 1, "chunk_id": "x", "doc_id": "d", "page": 1, "pos": 1,
                                           "cosine": 0.5}]  # fmt: skip
    assert rec["metrics"]["types"]["FAN_IN"] == {"n": 1, "hit3": 1.0, "recall10": 1.0}
    assert "sentence" not in str(rec)
