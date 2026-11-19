"""SCRUM-275-2 시트 손 실행 도구 — 리포 밖에만 씀(경로 우회 포함) · apply 도 초벌 완전성 점검 · 거절 때 안 씀.

DB·LLM 0(가짜 초벌·본문). 경로 테스트는 가짜 리포 폴더(tmp)를 REPO 로 둠.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.str import rag_answer_sheet as sheet
from tests.str import rag_answer_sheet_live as live
from tests.str import rag_answer_sheet_support as fx
from tests.str.rag_eval_v2_support import expand_answers, unchecked

_DB = (fx.DB, fx.TEXTS)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    r = tmp_path / "RepoDir"
    (r / "sub").mkdir(parents=True)
    monkeypatch.setattr(live, "REPO", r)
    return r


@pytest.fixture
def eval_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "eval"
    d.mkdir()
    monkeypatch.setattr(live, "EVAL_DIR", d)
    monkeypatch.setattr(live, "load_queries", lambda split: fx.QUERIES)
    return d


def test_inside_repo_plain_and_outside(repo: Path, tmp_path: Path) -> None:
    assert live.inside_repo(repo / "sub" / "new")
    assert not live.inside_repo(tmp_path / "outside" / "new")


def test_inside_repo_case_variant(repo: Path) -> None:
    variant = repo.parent / "repodir" / "sub"
    if not variant.exists():
        pytest.skip("대소문자를 구분하는 파일 시스템 — 변형 경로가 다른 폴더")
    assert live.inside_repo(variant / "new")


def test_inside_repo_relative_path(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo / "sub")
    assert live.inside_repo(Path("new"))
    assert live.inside_repo(Path("..") / "x")


def test_inside_repo_symlink(repo: Path, tmp_path: Path) -> None:
    (tmp_path / "outside").mkdir()
    link = tmp_path / "outside" / "link"
    os.symlink(repo / "sub", link)
    assert live.inside_repo(link / "new")
    assert live.inside_repo(link / ".." / "new")  # 링크/.. → 실제로는 리포 안


def test_export_refuses_inside_repo_and_writes_nothing(repo: Path) -> None:
    lines: list[str] = []
    assert live.export(repo / "sub", fx.draft(), _DB, fx.FP, out=lines.append) == 2
    assert not (repo / "sub" / live.SHEET_NAME).exists() and "리포 밖" in lines[0]


def test_export_writes_outside_and_prints_counts_only(tmp_path: Path) -> None:
    lines: list[str] = []
    assert live.export(tmp_path / "out", fx.draft(), _DB, fx.FP, out=lines.append) == 0
    assert (tmp_path / "out" / live.SHEET_NAME).exists() and (tmp_path / "out" / live.GUIDE_NAME).exists()
    assert lines == ["rows=4 CYCLE=3 FAN_IN=1 FAN_OUT=0"]
    assert (
        live.export(tmp_path / "out", fx.draft(), _DB, fx.FP, out=lines.append) == 1
    )  # 확인 중 시트를 안 덮음


def _csv(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "checked.csv"
    sheet.write_csv(path, records)
    return path


def _apply(path: Path, draft: dict, lines: list[str], checker: str = "확인자") -> int:
    return live.apply(path, checker, "2026-11-21", draft, _DB, fx.FP, out=lines.append)


def test_apply_writes_both_answer_files(tmp_path: Path, eval_dir: Path) -> None:
    assert _apply(_csv(tmp_path, fx.filled()), fx.draft(), []) == 0
    for split in live.SPLITS:
        doc = json.loads((eval_dir / f"answers_{split}.json").read_text(encoding="utf-8"))
        assert unchecked(doc) == []
        assert {e["check_scope"] for e in doc["queries"]} == {sheet.SCOPE_ALL, sheet.SCOPE_POSITIVE}


def test_apply_refuses_limit_one_draft_with_matching_partial_sheet(tmp_path: Path, eval_dir: Path) -> None:
    draft = fx.draft()
    draft["limit"], draft["chunks"] = 1, 1
    draft["graded_by_typology"] = {t: items[:1] for t, items in draft["graded_by_typology"].items()}
    partial = sheet.sheet_records(draft, fx.TEXTS, fx.FP)
    for r in partial:
        r["확인등급"] = r["LLM등급"]
    lines: list[str] = []
    assert _apply(_csv(tmp_path, partial), draft, lines) == 1
    assert not list(eval_dir.glob("answers_*.json")) and "전체 초벌" in lines[0]


def test_apply_refuses_empty_graded_with_empty_sheet(tmp_path: Path, eval_dir: Path) -> None:
    draft = {**fx.draft(), "graded_by_typology": {}}
    assert _apply(_csv(tmp_path, []), draft, []) == 1
    assert not list(eval_dir.glob("answers_*.json"))


def test_apply_rejects_bad_sheet_and_writes_nothing(tmp_path: Path, eval_dir: Path) -> None:
    records = fx.filled()
    records[0]["확인등급"] = ""
    lines: list[str] = []
    assert _apply(_csv(tmp_path, records), fx.draft(), lines) == 1
    assert not list(eval_dir.glob("answers_*.json")) and "반영 안 함" in lines[0]


def test_apply_replaces_unchecked_expand_output_but_not_checked(tmp_path: Path, eval_dir: Path) -> None:
    for split in live.SPLITS:
        doc = expand_answers(fx.draft(), fx.QUERIES)
        (eval_dir / f"answers_{split}.json").write_text(json.dumps(doc), encoding="utf-8")
    path = _csv(tmp_path, fx.filled())
    assert _apply(path, fx.draft(), [], checker="x") == 0
    lines: list[str] = []
    assert _apply(path, fx.draft(), lines, checker="y") == 1 and "이미 확인" in lines[0]
    doc = json.loads((eval_dir / "answers_dev.json").read_text(encoding="utf-8"))
    assert {e["checked_by"] for e in doc["queries"]} == {"x"}  # 두 번째 반영이 안 덮음


def test_apply_refuses_empty_checker(tmp_path: Path, eval_dir: Path) -> None:
    assert _apply(_csv(tmp_path, fx.filled()), fx.draft(), [], checker="  ") == 2


def _check_only(path: Path, lines: list[str]) -> int:
    return live.apply(path, "", "2026-11-21", fx.draft(), _DB, fx.FP, out=lines.append, check_only=True)


def test_check_only_blank_sheet_counts_and_writes_nothing(tmp_path: Path, eval_dir: Path) -> None:
    blank = sheet.sheet_records(fx.draft(), fx.TEXTS, fx.FP)  # 확인 전 시트 — 확인등급 전부 빈 칸
    lines: list[str] = []
    assert _check_only(_csv(tmp_path, blank), lines) == 0  # 빈 칸만 → 0
    assert any(line.strip().startswith("확인등급 빈 칸: 4") for line in lines)
    assert not any("본문 다름" in line for line in lines)
    assert not list(eval_dir.glob("answers_*.json"))


def test_check_only_reports_body_mismatch_count(tmp_path: Path, eval_dir: Path) -> None:
    records = fx.filled()
    records[0]["본문"], records[2]["본문"] = records[2]["본문"], records[0]["본문"]
    lines: list[str] = []
    assert _check_only(_csv(tmp_path, records), lines) == 1
    body = next(line for line in lines if "본문 다름" in line)
    assert body.strip().startswith("본문 다름: 2") and "행 2" in body and "행 4" in body
    assert not list(eval_dir.glob("answers_*.json"))


def test_check_only_clean_sheet_passes_without_checker(tmp_path: Path, eval_dir: Path) -> None:
    lines: list[str] = []
    assert _check_only(_csv(tmp_path, fx.filled()), lines) == 0
    assert "반영 가능" in lines[0] and not list(eval_dir.glob("answers_*.json"))


def test_check_only_fake_row_id_is_unknown_row_and_exit_one(tmp_path: Path, eval_dir: Path) -> None:
    from tests.str.rag_answer_sheet_check import BLANK, UNKNOWN

    fake = dict(sheet.sheet_records(fx.draft(), fx.TEXTS, fx.FP)[0], row_id=BLANK)
    lines: list[str] = []
    assert _check_only(_csv(tmp_path, [*fx.filled(), fake]), lines) == 1
    assert any(line.strip().startswith(f"{UNKNOWN}: 1") for line in lines)
