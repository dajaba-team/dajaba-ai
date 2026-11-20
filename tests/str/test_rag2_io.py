"""SCRUM-306 rag2_io — 셀 수 = 머리글 · Git 작업 트리 밖 · 새 파일만 · 확인자 폴더 검사 (추가 검토 1회차)."""

from __future__ import annotations

import subprocess

import pytest
from tools import rag2_io as io_
from tools.rag2_sample import ROOT


def test_read_rows_rejects_short_and_long_rows(tmp_path) -> None:
    p = tmp_path / "s.csv"
    p.write_text("a,b\n1,2\n1,2,3\n1\n", encoding="utf-8")
    with pytest.raises(io_.SheetError, match="3행 셀 3 ≠ 머리글 2 · 4행 셀 1 ≠ 머리글 2"):
        io_.read_rows(p)
    p.write_text('﻿a,b\n"x,y",2\n', encoding="utf-8")
    assert io_.read_rows(p) == (["a", "b"], [{"a": "x,y", "b": "2"}])  # 따옴표 안 쉼표는 한 셀


def test_in_worktree_sees_any_git_tree(tmp_path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    assert io_.in_worktree(ROOT / "nope" / "x.json") and io_.in_worktree(other / "deep" / "x.csv")
    assert not io_.in_worktree(tmp_path / "plain" / "x.csv")
    (tmp_path / "link").symlink_to(ROOT)
    assert io_.in_worktree(tmp_path / "link" / "x.csv")  # 링크를 풀고 봄


def test_write_new_never_overwrites(tmp_path) -> None:
    target = tmp_path / "x.json"
    io_.write_new(target, "1")
    with pytest.raises(ValueError, match="덮지 않음"):
        io_.write_new(target, "2")
    assert target.read_text(encoding="utf-8") == "1"
    with pytest.raises(ValueError, match="작업 트리 안"):
        io_.write_new(ROOT / "should_not_exist.json", "x")
    assert not (ROOT / "should_not_exist.json").exists()


def test_out_dir_problem(tmp_path) -> None:
    ok = {"sheet.csv"}
    assert io_.out_dir_problem(tmp_path / "new", ok) is None
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "sheet.csv").write_text("x", encoding="utf-8")
    (tmp_path / "c" / ".DS_Store").write_text("x", encoding="utf-8")
    assert io_.out_dir_problem(tmp_path / "c", ok) is None
    (tmp_path / "c" / "sheet_A.csv").write_text("x", encoding="utf-8")
    assert "확인자 단계 파일이 아닌" in io_.out_dir_problem(tmp_path / "c", ok)
    assert "블라인드" in io_.out_dir_problem(tmp_path / "blind_A", ok)
    assert "작업 트리" in io_.out_dir_problem(ROOT / "x", ok)
    assert "~" in io_.out_dir_problem("~/x", ok)
