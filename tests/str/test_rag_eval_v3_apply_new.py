"""SCRUM-306 확인 ②·③ 반영 — 두 시트 모두 통과해야 · 등급 ≥ 1 만 db_tagged=false · 이미 반영되면 거절."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from tools import rag2_consensus as rc
from tools.rag2_agreement import expected_rows

from tests.str import rag_eval_v3_apply_new as an
from tests.str import rag_eval_v3_round2 as r2
from tests.str.rag_eval_v3_decided import decided_new
from tests.str.rag_eval_v3_store import BUSY, locked
from tests.str.test_rag2_agreement import write_sheet
from tests.str.test_rag2_consensus import _decide
from tests.str.test_rag_eval_v3_round2 import A_TAGS, B_TAGS, _db, _read


@pytest.fixture(autouse=True)
def _fake_hash(monkeypatch) -> None:
    fake = lambda doc, page, text: text.removeprefix("body-")  # noqa: E731 — `body-<chunk_id>` = 그 청크 본문
    monkeypatch.setattr(r2, "compute_content_hash", fake)
    monkeypatch.setattr(rc, "compute_content_hash", fake)


def _fill(path: Path, grades: list[str]) -> None:
    rows = _read(path)
    for r, g in zip(rows, grades, strict=True):
        r["확인등급"] += g
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _setup(tmp_path: Path, c_grades: list[str], d_grades: list[str]) -> tuple[list[Path], Path]:
    a, b = write_sheet(tmp_path / "a.csv", A_TAGS), write_sheet(tmp_path / "b.csv", B_TAGS)
    pair = rc.load_pair(a, b)
    decided = _decide(rc.disagreement_rows(*pair), tmp_path / "d.csv")  # FAN_IN · 없음 · FAN_OUT
    new_c = r2.agreed_new(*pair, {})  # 0행 FAN_IN · 4행 FAN_OUT·SG
    new_d = decided_new(rc.load_decisions(decided, rc.disagreement_rows(*pair)), {})
    db = _db([c for _, c, _, _ in new_c + new_d])
    r2.write_grade_sheet(tmp_path / "c.csv", new_c, db, "C")
    r2.write_grade_sheet(tmp_path / "dg.csv", new_d, db, "D")
    _fill(tmp_path / "c.csv", c_grades)
    _fill(tmp_path / "dg.csv", d_grades)
    target = tmp_path / "cand.json"
    empty = {t: [] for t in ("FAN_IN", "FAN_OUT", "CYCLE", "SCATTER_GATHER", "GATHER_SCATTER")}
    doc = {
        "consensus_pending": True,
        "fan_checked_by": "김종민",
        "fan_checked_at": "2026-11-20",
        "candidates": empty,
    }
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return [a, b, decided, tmp_path / "c.csv", tmp_path / "dg.csv"], target


def test_apply_adds_grade_1_plus_as_not_db_tagged(tmp_path) -> None:
    sheets, target = _setup(tmp_path, ["2", "1", "0"], ["2", "0"])
    msgs: list[str] = []
    assert an.apply(sheets, "김종민", "2026-11-20", _db, target, msgs.append) == 0
    doc = json.loads(target.read_text(encoding="utf-8"))
    rows = [(t, r["source"], r["grade"], r["db_tagged"]) for t, rs in doc["candidates"].items() for r in rs]
    assert sorted(rows) == sorted([("FAN_IN", an.SOURCE_AGREED, 2, False), ("FAN_IN", an.SOURCE_DECIDED, 2, False),
                                   ("FAN_OUT", an.SOURCE_AGREED, 1, False)])  # fmt: skip
    ids = [r["chunk_id"] for r in expected_rows()]
    assert doc["candidates"]["FAN_IN"][0]["pos"] == int(expected_rows()[0]["쪽안_청크순번"])
    assert {r["chunk_id"] for r in doc["candidates"]["FAN_IN"]} == {ids[0], ids[1]}
    assert (doc["consensus_pending"], doc[an.CHECKED_BY], doc[an.CHECKED_AT]) == (
        False,
        "김종민",
        "2026-11-20",
    )
    assert msgs == [f"{an.SOURCE_AGREED}: graded=3 added=2 FAN_IN=1 FAN_OUT=1",
                    f"{an.SOURCE_DECIDED}: graded=2 added=1 FAN_IN=1"]  # fmt: skip
    before = target.read_bytes()
    assert an.apply(sheets, "김종민", "2026-11-20", _db, target, msgs.append) == 1
    assert target.read_bytes() == before


@pytest.mark.parametrize(("c", "d"), [(["2", "2", ""], ["2", "2"]), (["2", "2", "2"], ["2", "5"])])
def test_apply_refuses_if_either_sheet_bad(tmp_path, c, d) -> None:
    sheets, target = _setup(tmp_path, c, d)
    before = target.read_bytes()
    msgs: list[str] = []
    assert an.apply(sheets, "김종민", "2026-11-20", _db, target, msgs.append) == 1
    assert msgs[0].startswith("반영 안 함") and target.read_bytes() == before


def test_apply_refuses_db_mismatch_and_bad_args(tmp_path) -> None:
    sheets, target = _setup(tmp_path, ["2"] * 3, ["2"] * 2)
    victim = expected_rows()[0]["chunk_id"]

    def read(ids: list[str]) -> dict:
        db = _db(ids)
        db[victim] = (*db[victim][:2], "changed", [])
        return db

    msgs: list[str] = []
    assert an.apply(sheets, "김종민", "2026-11-20", read, target, msgs.append) == 1
    assert any(victim[:8] in m for m in msgs)
    assert an.apply(sheets, "", "2026-11-20", _db, target, lambda _m: None) == 2
    assert an.apply(sheets, "김종민", "11/20", _db, target, lambda _m: None) == 2


def test_apply_keeps_all_grade_records_including_zero(tmp_path) -> None:
    sheets, target = _setup(tmp_path, ["2", "1", "0"], ["2", "0"])
    assert an.apply(sheets, "김종민", "2026-11-20", _db, target, lambda _m: None) == 0
    doc = json.loads(target.read_text(encoding="utf-8"))
    recs = sorted((r["typology"], r["source"], r["grade"]) for r in doc[an.GRADES_KEY])
    assert len(recs) == 5 and [g for *_, g in recs].count(0) == 2  # 0 도 기록, 후보에는 안 넣음


def test_apply_refuses_before_fan_stage_and_when_locked(tmp_path) -> None:
    sheets, target = _setup(tmp_path, ["2"] * 3, ["2"] * 2)
    doc = json.loads(target.read_text(encoding="utf-8"))
    del doc["fan_checked_by"]
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    msgs: list[str] = []
    assert an.apply(sheets, "김종민", "2026-11-20", _db, target, msgs.append) == 1  # 역순 반영
    assert "① FAN" in msgs[0]
    target.write_text(json.dumps({**doc, "fan_checked_by": "김종민"}, ensure_ascii=False), encoding="utf-8")
    before = target.read_bytes()
    with locked(target):
        assert an.apply(sheets, "김종민", "2026-11-20", _db, target, msgs.append) == 1
    assert msgs[-1] == BUSY and target.read_bytes() == before


def test_apply_stops_when_sample_chunk_got_db_tag(tmp_path) -> None:
    """표본 동결(무태그) 뒤 DB 에 태그가 생긴 청크 — db_tagged 를 false 로 단정하지 않고 반영 전체 중단."""
    sheets, target = _setup(tmp_path, ["2"] * 3, ["2"] * 2)
    victim = expected_rows()[0]["chunk_id"]

    def read(ids: list[str]) -> dict:
        db = _db(ids)
        db[victim] = (*db[victim][:3], ["FAN_IN"])
        return db

    before = target.read_bytes()
    msgs: list[str] = []
    assert an.apply(sheets, "김종민", "2026-11-20", read, target, msgs.append) == 1
    assert any("동결" in m and victim[:8] in m for m in msgs) and target.read_bytes() == before
