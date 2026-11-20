"""SCRUM-306 확인 시트 ① 반영 — 등급 칸 ID 대조 · 행·본문 대조 · 틀리면 반영 0 · 이미 반영되면 거절."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from tests.str import rag_eval_v3_apply as ap
from tests.str import rag_eval_v3_sheet as vs
from tests.str.rag_eval_v3_store import BUSY, locked
from tests.str.test_rag_eval_v3_sheet import _fake, _rows


def _setup(tmp_path: Path, grades: list[str]) -> tuple[Path, Path, dict]:
    cands, db = _fake()
    assert vs.export_fan(tmp_path / "c", cands, db, lambda _m: None) == 0
    sheet = tmp_path / "c" / vs.SHEET_NAME
    rows = _rows(sheet)
    for r, g in zip(rows, grades, strict=True):
        r["확인등급"] += g
        r["메모"] = "짧은 이유"
    with sheet.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    target = tmp_path / "answer_candidates.json"
    rows_of = {t: [{**c, "grade": None} for c in cands[t]] for t in cands}
    target.write_text(json.dumps({"candidates": rows_of}, ensure_ascii=False), encoding="utf-8")
    return sheet, target, db


def test_apply_writes_fan_grades_and_checker(tmp_path) -> None:
    sheet, target, db = _setup(tmp_path, ["2", "1", "0", "1", "0"])
    msgs: list[str] = []
    assert ap.apply_fan(sheet, "김종민", "2026-11-20", db, target, msgs.append) == 0
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert [r["grade"] for r in doc["candidates"]["FAN_IN"]] == [2, 1, 0]
    assert [r["grade"] for r in doc["candidates"]["FAN_OUT"]] == [1, 0]
    assert (doc[ap.CHECKED_BY], doc[ap.CHECKED_AT]) == ("김종민", "2026-11-20")
    assert msgs == ["FAN_IN: rows=3 0=1 1=1 2=1", "FAN_OUT: rows=2 0=1 1=1 2=0"]  # 개수만, 메모 0
    before = target.read_bytes()
    assert ap.apply_fan(sheet, "김종민", "2026-11-20", db, target, msgs.append) == 1  # 이미 반영
    assert target.read_bytes() == before


@pytest.mark.parametrize(
    ("grades", "spoil", "msg"),
    [
        (["2", "1", "", "1", "0"], None, "FI-003: 등급 칸"),
        (["2", "1", "3", "1", "0"], None, "FI-003: 등급 칸"),
        (["2", "1", "1;2", "1", "0"], None, "FI-003: 등급 칸"),
        (
            ["2"] * 5,
            lambda r: r[2].update({"확인등급": f"{vs.grade_key('FAN_IN', r[0]['chunk_id'])}=1"}),
            "FI-003: 등급 칸",
        ),
        (["2"] * 5, lambda r: r[1].update({"본문": "바뀐 본문"}), "FI-002: 본문"),
        (["2"] * 5, lambda r: r.__setitem__(slice(0, 2), [r[1], r[0]]), "FI-001: 행"),
        (["2"] * 5, lambda r: r.pop(), "행 수 4"),
    ],
)
def test_apply_refuses_and_writes_nothing(tmp_path, grades, spoil, msg) -> None:
    sheet, target, db = _setup(tmp_path, grades)
    if spoil:
        rows = _rows(sheet)
        spoil(rows)
        with sheet.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    before = target.read_bytes()
    msgs: list[str] = []
    assert ap.apply_fan(sheet, "김종민", "2026-11-20", db, target, msgs.append) == 1
    assert any(msg in m for m in msgs) and target.read_bytes() == before


def test_apply_refuses_bad_args(tmp_path) -> None:
    sheet, target, db = _setup(tmp_path, ["1"] * 5)
    assert ap.apply_fan(sheet, " ", "2026-11-20", db, target, lambda _m: None) == 2
    assert ap.apply_fan(sheet, "김종민", "11/20", db, target, lambda _m: None) == 2


def test_apply_refuses_extra_cell_in_grade_row(tmp_path) -> None:
    """`ID=1,2` 처럼 쉼표로 칸이 밀린 등급 행 — 앞 값만 읽지 않고 거절."""
    sheet, target, db = _setup(tmp_path, ["2", "1", "0", "1", "0"])
    key = vs.grade_key("FAN_IN", _rows(sheet)[0]["chunk_id"])
    raw = sheet.read_bytes().decode("utf-8-sig")
    sheet.write_bytes(raw.replace(f"{key}=2,", f"{key}=1,2,", 1).encode("utf-8-sig"))
    before = target.read_bytes()
    msgs: list[str] = []
    assert ap.apply_fan(sheet, "김종민", "2026-11-20", db, target, msgs.append) == 1
    assert any("셀 9 ≠ 머리글 8" in m for m in msgs) and target.read_bytes() == before


def test_apply_refuses_when_later_stage_or_lock_present(tmp_path) -> None:
    sheet, target, db = _setup(tmp_path, ["1"] * 5)
    doc = json.loads(target.read_text(encoding="utf-8"))
    target.write_text(json.dumps({**doc, ap.LATER_STAGE: "x"}, ensure_ascii=False), encoding="utf-8")
    msgs: list[str] = []
    assert ap.apply_fan(sheet, "김종민", "2026-11-20", db, target, msgs.append) == 1
    assert "순서" in msgs[0]
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    before = target.read_bytes()
    with locked(target):  # 다른 반영이 잡고 있으면 기다리지 않고 거절
        assert ap.apply_fan(sheet, "김종민", "2026-11-20", db, target, msgs.append) == 1
    assert msgs[-1] == BUSY and target.read_bytes() == before
    assert ap.apply_fan(sheet, "김종민", "2026-11-20", db, target, msgs.append) == 0
    assert not list(target.parent.glob(f".{target.name}.*.tmp"))  # 임시 파일 안 남음


def test_apply_touches_only_fan_source_rows(tmp_path) -> None:
    sheet, target, db = _setup(tmp_path, ["2"] * 5)
    doc = json.loads(target.read_text(encoding="utf-8"))
    extra = {"chunk_id": "e" * 64, "doc_id": "doc-x", "page": 9, "source": "합의_태그", "grade": 2}
    doc["candidates"]["FAN_IN"].append(extra)
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert ap.apply_fan(sheet, "김종민", "2026-11-20", db, target, lambda _m: None) == 0
    rows = json.loads(target.read_text(encoding="utf-8"))["candidates"]["FAN_IN"]
    assert rows[-1] == extra and [r["grade"] for r in rows[:-1]] == [2, 2, 2]
