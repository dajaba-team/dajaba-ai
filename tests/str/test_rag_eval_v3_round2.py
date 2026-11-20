"""SCRUM-306 확인 ② — 불일치 목록 `본문`(해시 대조 뒤) · 합의 새 행(같은 태그·후보 밖) 시트 · 리포 밖·덮지 않음."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from tools import rag2_consensus as rc
from tools.rag2_agreement import expected_rows
from tools.rag2_sample import ROOT

from tests.str import rag_calibration_sheet as cal
from tests.str import rag_eval_v3_round2 as r2
from tests.str.test_rag2_agreement import write_sheet

A_TAGS = {0: "FAN_IN", 1: "FAN_IN;GS", 2: "CYCLE", 4: "FAN_OUT;SG"}
B_TAGS = {0: "FAN_IN", 1: "FAN_IN", 3: "FAN_OUT", 4: "FAN_OUT;SG"}  # 0·4 같음, 1·2·3 다름


@pytest.fixture(autouse=True)
def _fake_hash(monkeypatch) -> None:
    fake = lambda doc, page, text: text.removeprefix("body-")  # noqa: E731 — `body-<chunk_id>` = 그 청크 본문
    monkeypatch.setattr(r2, "compute_content_hash", fake)
    monkeypatch.setattr(rc, "compute_content_hash", fake)


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    return write_sheet(tmp_path / "a.csv", A_TAGS), write_sheet(tmp_path / "b.csv", B_TAGS)


def _db(ids: list[str]) -> dict:
    base = {r["chunk_id"]: r for r in expected_rows()}
    return {c: (base[c]["doc_id"], int(base[c]["page"]), f"body-{c}", []) for c in ids}


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_export_writes_both_sheets_and_note(tmp_path) -> None:
    ids = [r["chunk_id"] for r in expected_rows()]
    have = {"FAN_IN": [{"chunk_id": ids[0]}]}  # 0행 FAN_IN 은 이미 후보 → 빠짐
    msgs: list[str] = []
    assert r2.export(_pair(tmp_path), tmp_path / "c", have, _db, msgs.append) == 0
    dis = _read(tmp_path / "c" / r2.DISAGREE_NAME)
    assert list(dis[0]) == rc.DISAGREE_FIELDS and [r["chunk_id"] for r in dis] == ids[1:4]
    assert all(r[rc.TEXT_FIELD] == f"body-{r['chunk_id']}" for r in dis)
    sheet = _read(tmp_path / "c" / r2.CONSENSUS_SHEET)
    assert list(sheet[0]) == cal.COLUMNS
    assert [(r["행"], r["유형"], r["chunk_id"]) for r in sheet] == [
        ("C-FO-001", "FAN_OUT", ids[4]), ("C-SG-001", "SCATTER_GATHER", ids[4])]  # fmt: skip
    assert [r["확인등급"] for r in sheet] == [f"FO-{ids[4][:8]}=", f"SG-{ids[4][:8]}="]
    note = (tmp_path / "c" / "README_306.md").read_text(encoding="utf-8")
    assert note.count(r2.NOTE_MARK) == 1 and "이유분류" in note and "기준 모호" in note
    assert msgs == [f"disagree=3 → {r2.DISAGREE_NAME} · consensus_new=2 → {r2.CONSENSUS_SHEET}"]


def test_export_appends_note_once_and_refuses_overwrite(tmp_path) -> None:
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "README_306.md").write_text("# 확인 ①\n", encoding="utf-8")
    assert r2.export(_pair(tmp_path), tmp_path / "c", {}, _db, lambda _m: None) == 0
    note = (tmp_path / "c" / "README_306.md").read_text(encoding="utf-8")
    assert note.startswith("# 확인 ①\n") and note.count(r2.NOTE_MARK) == 1
    before = (tmp_path / "c" / r2.DISAGREE_NAME).read_bytes()
    assert r2.export(_pair(tmp_path), tmp_path / "c", {}, _db, lambda _m: None) == 1
    assert (tmp_path / "c" / r2.DISAGREE_NAME).read_bytes() == before


@pytest.mark.parametrize(
    "spoil",
    [lambda db, c: db.pop(c), lambda db, c: db.__setitem__(c, ("doc-y", *db[c][1:])),
     lambda db, c: db.__setitem__(c, (*db[c][:2], "changed", []))],
)  # fmt: skip
def test_export_refuses_db_mismatch_and_writes_nothing(tmp_path, spoil) -> None:
    victim = expected_rows()[2]["chunk_id"]

    def read(ids: list[str]) -> dict:
        db = _db(ids)
        spoil(db, victim)
        return db

    msgs: list[str] = []
    assert r2.export(_pair(tmp_path), tmp_path / "c", {}, read, msgs.append) == 1
    assert msgs == [f"DB 원본과 다른 청크: ['{victim[:8]}']"] and not (tmp_path / "c").exists()


def test_export_refuses_repo_path(tmp_path) -> None:
    assert r2.export(_pair(tmp_path), ROOT / "round2_should_not_exist", {}, _db, lambda _m: None) == 2
    assert not (ROOT / "round2_should_not_exist").exists()


@pytest.mark.parametrize("bad", ["blind_A", "returned", "other_tree"])
def test_all_exports_refuse_wrong_folder_before_writing(tmp_path, bad) -> None:
    """①②③ 내보내기 공통 — 블라인드 묶음 · 받은 시트가 있는 폴더 · 다른 Git 작업 트리면 본문 쓰기 전 거절."""
    import subprocess

    from tests.str import rag_eval_v3_decided as dc
    from tests.str import rag_eval_v3_sheet as vs
    from tests.str.test_rag_eval_v3_sheet import _fake

    target = tmp_path / bad
    target.mkdir()
    if bad == "returned":
        (target / "sheet_A.csv").write_text("x", encoding="utf-8")
    if bad == "other_tree":
        subprocess.run(["git", "init", "-q", str(target)], check=True)
    before = sorted(p.name for p in target.iterdir())
    a, b = _pair(tmp_path)
    msgs: list[str] = []
    assert r2.export((a, b), target, {}, _db, msgs.append) == 2
    assert dc.export((a, b, a), target, {}, _db, msgs.append) == 2
    assert vs.export_fan(target, *_fake(), msgs.append) == 2
    assert sorted(p.name for p in target.iterdir()) == before and len(msgs) == 3
