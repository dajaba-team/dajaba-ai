"""SCRUM-306 정답 확인 시트 ① FAN — 305 방식 칸·행ID·등급 칸 · DB 원본 대조 · 리포 밖·덮지 않음."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from tools.corpus_chunks import compute_content_hash
from tools.rag2_sample import ROOT

from tests.str import rag_calibration_sheet as cal
from tests.str import rag_eval_v3_sheet as vs
from tests.str.rag_eval_v3_candidates import CANDIDATES_FILE
from tests.str.rag_eval_v3_sheet import fan_rows


def _fake(n_in: int = 3, n_out: int = 2) -> tuple[dict, dict]:
    cands: dict = {"FAN_IN": [], "FAN_OUT": []}
    db: dict = {}
    for typ, n in (("FAN_IN", n_in), ("FAN_OUT", n_out)):
        for i in range(n):
            body = f"{typ} body {i}."
            cid = compute_content_hash("doc-x", i + 1, body)
            cands[typ].append({"chunk_id": cid, "doc_id": "doc-x", "page": i + 1})
            db[cid] = ("doc-x", i + 1, body, [typ])
    return cands, db


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_export_writes_305_style_sheet(tmp_path) -> None:
    cands, db = _fake()
    msgs: list[str] = []
    assert vs.export_fan(tmp_path / "c", cands, db, msgs.append) == 0
    assert {p.name for p in (tmp_path / "c").iterdir()} == {
        vs.SHEET_NAME,
        cal.GUIDE_NAME,
        cal.CRITERIA_NAME,
        vs.NOTE_NAME,
    }
    rows = _rows(tmp_path / "c" / vs.SHEET_NAME)
    assert list(rows[0]) == cal.COLUMNS
    assert [r["행"] for r in rows] == ["FI-001", "FI-002", "FI-003", "FO-001", "FO-002"]
    assert all(
        r["확인등급"] == f"{vs.grade_key(r['유형'], r['chunk_id'])}=" and r["메모"] == "" for r in rows
    )
    assert [r["본문"] for r in rows][:1] == ["FAN_IN body 0."]
    assert msgs == [f"rows=5 FAN_IN=3 FAN_OUT=2 → {vs.SHEET_NAME}"]  # 출력은 개수만
    note = (tmp_path / "c" / vs.NOTE_NAME).read_text(encoding="utf-8")
    assert "FAN_OUT 5행" in note and "기준 맞추기 없음" in note


@pytest.mark.parametrize(
    "spoil",
    [
        lambda db, c: db.pop(c),
        lambda db, c: db.__setitem__(c, ("doc-y", *db[c][1:])),
        lambda db, c: db.__setitem__(c, (db[c][0], 99, *db[c][2:])),
        lambda db, c: db.__setitem__(c, (*db[c][:3], ["CYCLE"])),
        lambda db, c: db.__setitem__(c, (db[c][0], db[c][1], "changed body", db[c][3])),
    ],
)
def test_export_refuses_db_mismatch(tmp_path, spoil) -> None:
    cands, db = _fake()
    spoil(db, cands["FAN_IN"][1]["chunk_id"])
    msgs: list[str] = []
    assert vs.export_fan(tmp_path / "c", cands, db, msgs.append) == 1
    assert msgs == ["DB 원본과 다른 행: ['FI-002']"] and not (tmp_path / "c").exists()


def test_export_refuses_repo_path_tilde_and_overwrite(tmp_path) -> None:
    cands, db = _fake()
    assert vs.export_fan(ROOT / "checker_should_not_exist", cands, db, lambda _m: None) == 2
    assert not (ROOT / "checker_should_not_exist").exists()
    assert vs.export_fan(Path("~/x"), cands, db, lambda _m: None) == 2
    assert vs.export_fan(tmp_path / "c", cands, db, lambda _m: None) == 0
    before = (tmp_path / "c" / vs.SHEET_NAME).read_bytes()
    assert vs.export_fan(tmp_path / "c", cands, db, lambda _m: None) == 1
    assert (tmp_path / "c" / vs.SHEET_NAME).read_bytes() == before


def test_repo_candidates_give_25_fan_rows() -> None:
    rows = fan_rows(json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))["candidates"])
    assert len(rows) == 25 and sum(r[1] == "FAN_IN" for r in rows) == 19
    assert len({vs.grade_key(t, c) for _, t, c, _, _ in rows}) == 25  # 등급 칸 ID 가 겹치지 않음
