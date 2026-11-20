"""SCRUM-306 추가 검토 2회차 회귀 — 05·06·후보 파일이 잘못된 입력으로 줄거나 바뀌지 않음 · 정상 시트는 통과."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest
from tools import rag2_agreement as ag
from tools import rag2_consensus as rc
from tools import rag2_proposal as rp
from tools import rag2_sample_new as rn
from tools.rag2_sample import ROOT, SAMPLE_CSV

from tests.str import rag_eval_v3_apply_new as an
from tests.str import rag_eval_v3_round2 as r2
from tests.str import rag_eval_v3_sheet as vs
from tests.str.test_rag2_agreement import evidence_in, write_sheet
from tests.str.test_rag2_consensus import _decide
from tests.str.test_rag2_proposal import _pages
from tests.str.test_rag_eval_v3_apply_new import _setup
from tests.str.test_rag_eval_v3_round2 import A_TAGS, _db
from tests.str.test_rag_eval_v3_sheet import _fake


@pytest.fixture(autouse=True)
def _fake_hash(monkeypatch) -> None:
    fake = lambda doc, page, text: text.removeprefix("body-")  # noqa: E731 — `body-<chunk_id>` = 그 청크 본문
    monkeypatch.setattr(r2, "compute_content_hash", fake)
    monkeypatch.setattr(rc, "compute_content_hash", fake)


def _sample_rows() -> list[dict[str, str]]:
    with SAMPLE_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_write_80_refuses_and_keeps_bytes(tmp_path) -> None:
    rows = _sample_rows()
    target = tmp_path / "05.csv"
    assert rn.write_80(rows, target) == "wrote" and rn.write_80(rows, target) == "same"
    before = target.read_bytes()
    bad = {"70행": rows[:70], "중복": [*rows[:79], rows[0]], "앞 70 바뀜": [{**rows[0], "끝": "1"}, *rows[1:]],
           "기존과 다름": [*rows[:79], {**rows[79], "끝": "1"}]}  # fmt: skip
    for name, given in bad.items():
        with pytest.raises(ValueError, match="고유|동결|다름"):
            rn.write_80(given, target)
        assert target.read_bytes() == before, name
    assert not list(tmp_path.glob(".05.csv.*.tmp"))


def test_proposal_refuses_when_records_disagree(tmp_path) -> None:
    a, b = write_sheet(tmp_path / "a.csv", A_TAGS), write_sheet(tmp_path / "b.csv", {0: "FAN_IN"})
    decided = _decide(rc.disagreement_rows(*rc.load_pair(a, b)), tmp_path / "d.csv", {})
    agreed = rc.consensus(
        *rc.load_pair(a, b), rc.load_decisions(decided, rc.disagreement_rows(*rc.load_pair(a, b)))
    )
    ids = [r["chunk_id"] for r in ag.expected_rows()]
    recs = [{"typology": rp.SHEET_TO_TYPE[t], "chunk_id": c, "source": "합의_태그" if c == ids[0] else "결정_태그", "grade": 0}
            for c, tags in agreed.items() for t in tags]  # fmt: skip
    doc = {"candidates": {}, "consensus_grades": recs}
    assert len(rp.proposal_rows((a, b, decided), doc, _pages())) == 3  # 정상: 기록 = 제안
    for spoil in (
        {**doc, "consensus_grades": [*recs, {**recs[0], "chunk_id": "x" * 64}]},  # 기록에만 있는 행
        {**doc, "consensus_grades": [{**recs[0], "source": "결정_태그"}, *recs[1:]]},
    ):  # 출처 변경
        with pytest.raises(rp.Unchecked, match="기록과 제안이 다름"):
            rp.proposal_rows((a, b, decided), spoil, _pages())


def test_proposal_refuses_when_05_position_moved(tmp_path) -> None:
    pages = _pages()
    first = ag.expected_rows()[0]
    key = (first["doc_id"], int(first["page"]))
    pages[key] = [(p + 100, c) if c == first["chunk_id"] else (p, c) for p, c in pages[key]]
    with pytest.raises(rp.Unchecked, match="05 위치"):
        rp.proposal_rows((tmp_path / "a", tmp_path / "b", tmp_path / "d"), {"candidates": {}}, pages)


def test_exports_refuse_blind_ancestor_and_foreign_guide(tmp_path) -> None:
    cands, db = _fake()
    assert vs.export_fan(tmp_path / "blind_A" / "checker", cands, db, lambda _m: None) == 2
    assert not (tmp_path / "blind_A").exists()
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / vs.cal.GUIDE_NAME).write_text("다른 안내", encoding="utf-8")
    msgs: list[str] = []
    assert vs.export_fan(tmp_path / "c", cands, db, msgs.append) == 1 and "기대 내용과 다름" in msgs[0]
    assert not (tmp_path / "c" / vs.SHEET_NAME).exists()  # CSV 만들기 전 멈춤
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / vs.cal.CRITERIA_NAME).symlink_to(tmp_path / "elsewhere.md")
    assert vs.export_fan(tmp_path / "d", cands, db, msgs.append) == 1 and "심볼릭" in msgs[-1]


def test_readme_keeps_other_stage_section(tmp_path) -> None:
    (tmp_path / "c").mkdir()
    note = tmp_path / "c" / vs.NOTE_NAME
    note.write_text(f"{r2.NOTE_MARK} — 이미 있는 ② 절\n", encoding="utf-8")
    assert vs.export_fan(tmp_path / "c", *_fake(), lambda _m: None) == 0
    text = note.read_text(encoding="utf-8")
    assert text.startswith(f"{r2.NOTE_MARK} — 이미 있는 ② 절") and vs.NOTE_MARK_1 in text


@pytest.mark.parametrize("case", ["sample_tagged", "sample_gone", "candidate_drift", "fan_unfinished"])
def test_final_apply_checks_whole_sample_and_candidates(tmp_path, case) -> None:
    sheets, target = _setup(tmp_path, ["2"] * 3, ["2"] * 2)
    doc = json.loads(target.read_text(encoding="utf-8"))
    old = {
        "chunk_id": "o" * 64,
        "doc_id": "doc-o",
        "page": 1,
        "pos": 1,
        "source": "FAN_태그",
        "grade": 1,
        "db_tagged": True,
    }
    doc["candidates"]["FAN_IN"].append({**old, "grade": None} if case == "fan_unfinished" else old)
    target.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    untouched = ag.expected_rows()[60]["chunk_id"]  # 등급 시트에 안 들어가는 표본 행

    def read(ids: list[str]) -> dict:
        db = {**_db([i for i in ids if i != old["chunk_id"]]), old["chunk_id"]: ("doc-o", 1, "t", ["FAN_IN"])}
        if case == "sample_tagged":
            db[untouched] = (*db[untouched][:3], ["CYCLE"])
        if case == "sample_gone":
            db.pop(untouched)
        if case == "candidate_drift":
            db[old["chunk_id"]] = ("doc-o", 1, "t", [])
        return db

    before = target.read_bytes()
    msgs: list[str] = []
    assert an.apply(sheets, "김종민", "2026-11-20", read, target, msgs.append) == 1
    assert target.read_bytes() == before
    want = {
        "sample_tagged": "동결",
        "sample_gone": "DB 에 없는",
        "candidate_drift": "db_tagged",
        "fan_unfinished": "① FAN",
    }
    assert any(want[case] in m for m in msgs)


def test_same_content_after_crlf_and_spacing_is_rejected(tmp_path) -> None:
    rows = ag.expected_rows()
    ev = evidence_in(rows[0])
    a = write_sheet(
        tmp_path / "a.csv", {0: "FAN_IN"}, rows=lambda r: [{**r[0], "메모": "한 줄\n두 줄"}, *r[1:]]
    )
    b = write_sheet(tmp_path / "b.csv", {0: "FAN_IN"},
                    rows=lambda r: [{**r[0], "메모": "한 줄\r\n두 줄 ", "근거위치": ev.replace(" ", "·")}, *r[1:]])  # fmt: skip
    with pytest.raises(ag.SheetError, match="같음"):
        rc.load_pair(a, b)


def test_middle_dot_evidence_is_accepted(tmp_path) -> None:
    row = ag.expected_rows()[0]
    dot = evidence_in(row).replace(" ", "·")
    got = ag.load_sheet(
        write_sheet(tmp_path / "a.csv", rows=lambda r: [{**r[0], "태그": "FAN_IN", "근거위치": dot}, *r[1:]])
    )
    assert got[0].tags == {"FAN_IN"}


def test_errors_never_echo_cell_values(tmp_path) -> None:
    """머리글이 빠진 결정 시트 · 모르는 태그 — stdout·stderr 에 본문·근거·태그 글자 0."""
    a, b = write_sheet(tmp_path / "a.csv", A_TAGS), write_sheet(tmp_path / "b.csv", {0: "FAN_IN"})
    listed = rc.disagreement_rows(*rc.load_pair(a, b))
    decided = _decide(
        listed, tmp_path / "d.csv", {0: {rc.TEXT_FIELD: "SECRET-BODY", "A_근거위치": "SECRET-EV"}}
    )
    decided.write_text(
        "".join(decided.read_text(encoding="utf-8").splitlines(keepends=True)[1:]), encoding="utf-8"
    )
    cmd = [sys.executable, "-m", "tools.rag2_consensus", "consensus", str(a), str(b), str(decided),
           "--out", str(tmp_path / "r.json"), "--checker", "확인자", "--checked-at", "2026-11-20"]  # fmt: skip
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    assert done.returncode != 0 and "칸이 다름" in done.stderr
    assert "SECRET" not in done.stdout + done.stderr
    bad = write_sheet(tmp_path / "x.csv", rows=lambda r: [{**r[0], "태그": "SECRET-TAG"}, *r[1:]])
    with pytest.raises(ag.SheetError) as err:
        ag.load_sheet(bad)
    assert "SECRET" not in str(err.value) and "모르는 태그" in str(err.value)


def test_real_05_untouched_by_tools() -> None:
    assert rn.write_80(_sample_rows(), Path(SAMPLE_CSV)) == "same"  # 정본은 같은 내용이면 그대로
