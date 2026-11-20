"""SCRUM-305 기준 맞추기 시트 (docs/str/10 "기준 맞추기" · "305 실행 기록"). DB 0 — 본문은 합성 dict.

시트에는 등급 칸이 비어 있고(LLM·준혁 등급 둘 다 없음) 리포 밖 폴더에만 쓴다. 대조는 준혁 등급과 "1 이상인가".
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from tests.str import rag_calibration_sheet as cal
from tests.str.rag_eval_corpus_draw import calibration_population

REPO = Path(__file__).parents[2]
ROUND1 = cal.round_rows(1)
TEXTS = {r["chunk_id"]: f"본문 {r['chunk_id'][:6]}" for r in ROUND1}
_GRADE = {(r["typology"], r["chunk_id"]): r["grade"] for r in calibration_population()}


def _export(tmp_path: Path) -> Path:
    out: list[str] = []
    assert cal.export_calibration(tmp_path / "sheet", 1, TEXTS, out=out.append) == 0
    return tmp_path / "sheet" / cal.SHEET_NAME


def _fill(path: Path, grade_of) -> None:  # noqa: ANN001
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    for r in rows:
        r["확인등급"] = str(grade_of(r))
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cal.COLUMNS)
        w.writeheader()
        w.writerows(rows)


def test_export_writes_25_rows_without_grades(tmp_path: Path) -> None:
    path = _export(tmp_path)
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    assert len(rows) == 25 and list(rows[0]) == cal.COLUMNS
    assert all(r["확인등급"] == "" for r in rows)
    assert [r["행"] for r in rows] == [r["row_id"] for r in ROUND1]
    raw = path.read_text(encoding="utf-8-sig").lower()
    assert "llm" not in raw and "grade" not in raw
    for name in (cal.GUIDE_NAME, cal.CRITERIA_NAME):  # 04 가 함정 목록을 00 으로 가리킴 — 둘 다 같은 폴더
        assert (tmp_path / "sheet" / name).read_text(encoding="utf-8").startswith("#")
    assert cal.CRITERIA_NAME == "00_tagging_criteria.md" and "확인등급" in cal.COLUMNS


def test_export_refuses_repo_folder_and_overwrite(tmp_path: Path) -> None:
    out: list[str] = []
    assert cal.export_calibration(REPO / "tmp_sheet", 1, TEXTS, out=out.append) == 2
    assert not (REPO / "tmp_sheet").exists()
    _export(tmp_path)
    assert cal.export_calibration(tmp_path / "sheet", 1, TEXTS, out=out.append) == 1


def test_export_refuses_missing_chunk_text(tmp_path: Path) -> None:
    out: list[str] = []
    texts = dict(TEXTS)
    texts.pop(ROUND1[0]["chunk_id"])
    assert cal.export_calibration(tmp_path / "sheet", 1, texts, out=out.append) == 1


@pytest.mark.parametrize(("flips", "same"), [(0, True), (5, True), (6, False)])
def test_check_counts_agreement_with_reference(tmp_path: Path, flips: int, same: bool) -> None:
    path = _export(tmp_path)
    order = [r["row_id"] for r in ROUND1]

    def grade(r: dict) -> int:
        g = _GRADE[(r["유형"], r["chunk_id"])]
        return (0 if g >= 1 else 1) if order.index(r["행"]) < flips else g

    _fill(path, grade)
    out: list[str] = []
    code = cal.check_calibration(path, 1, TEXTS, out=out.append)
    assert code == (0 if same else 1)
    assert f"matches={25 - flips}" in out[-1]


@pytest.mark.parametrize("bad", ["", "3", "x"])
def test_check_rejects_blank_or_bad_grade(tmp_path: Path, bad: str) -> None:
    path = _export(tmp_path)
    _fill(path, lambda r: bad if r["행"] == ROUND1[0]["row_id"] else 0)
    out: list[str] = []
    assert cal.check_calibration(path, 1, TEXTS, out=out.append) == 2


def test_check_rejects_changed_rows(tmp_path: Path) -> None:
    path = _export(tmp_path)
    _fill(path, lambda r: 0)
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    rows[0]["chunk_id"] = "0" * 64
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cal.COLUMNS)
        w.writeheader()
        w.writerows(rows)
    out: list[str] = []
    assert cal.check_calibration(path, 1, TEXTS, out=out.append) == 2


def test_quoted_tilde_out_is_refused_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """추가 검토 2 ③ — 리포 루트에서 --out "~/sheet"(셸이 안 푼 ~). 검사·쓰기 경로가 갈리지 않게 거절."""
    import argparse

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(REPO)
    out: list[str] = []
    args = argparse.Namespace(cmd="export-calibration", out=Path("~/sheet"), round=1)
    assert cal.run_command(args, lambda: TEXTS) == 2
    assert cal.export_calibration(Path("~/sheet"), 1, TEXTS, out=out.append) == 2
    assert not (REPO / "~").exists() and not (home / "sheet").exists()


def test_export_writes_to_the_checked_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """상대 경로도 한 번 정규화한 같은 경로에 씀."""
    monkeypatch.chdir(tmp_path)
    out: list[str] = []
    assert cal.export_calibration(Path("rel") / ".." / "sheet2", 1, TEXTS, out=out.append) == 0
    assert (tmp_path / "sheet2" / cal.SHEET_NAME).is_file()
