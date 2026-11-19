"""SCRUM-275-2 정답 두 파일 함께 쓰기 (추가 검토 2) — 두 번째 쓰기·교체 실패 때 둘 다 원래대로, 임시·백업 안 남음."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.str import rag_answer_sheet_io as io


def _targets(tmp_path: Path) -> tuple[Path, Path]:
    return tmp_path / "answers_dev.json", tmp_path / "answers_holdout.json"


def _leftovers(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("."))


def test_success_writes_both_and_leaves_nothing(tmp_path: Path) -> None:
    dev, hold = _targets(tmp_path)
    dev.write_text("old-dev", encoding="utf-8")
    io.write_pair({dev: "new-dev", hold: "new-hold"})
    assert dev.read_text(encoding="utf-8") == "new-dev" and hold.read_text(encoding="utf-8") == "new-hold"
    assert _leftovers(tmp_path) == []


def _fail_on_second(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    real = getattr(io if name == "_write_temp" else os, name)
    calls: list[int] = []

    def flaky(*args: object, **kwargs: object) -> object:
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        return real(*args, **kwargs)

    if name == "_write_temp":
        monkeypatch.setattr(io, "_write_temp", flaky)
    else:
        monkeypatch.setattr(io.os, "replace", flaky)


@pytest.mark.parametrize("where", ["_write_temp", "replace"])
@pytest.mark.parametrize("had_files", [True, False])
def test_second_failure_restores_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, where: str, had_files: bool
) -> None:
    dev, hold = _targets(tmp_path)
    if had_files:
        dev.write_text("old-dev", encoding="utf-8")
        hold.write_text("old-hold", encoding="utf-8")
    _fail_on_second(monkeypatch, where)
    with pytest.raises(OSError, match="disk full"):
        io.write_pair({dev: "new-dev", hold: "new-hold"})
    if had_files:
        assert dev.read_text(encoding="utf-8") == "old-dev" and hold.read_text(encoding="utf-8") == "old-hold"
    else:
        assert not dev.exists() and not hold.exists()
    assert _leftovers(tmp_path) == []
