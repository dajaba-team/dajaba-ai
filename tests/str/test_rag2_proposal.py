"""SCRUM-306 적용 제안 (03 6절 4번) — 붙은 합의 행만 · 0·1·2 기록 그대로 · 미확인이면 멈춤 · 이웃청크 · 청크/쪽 단위 수."""

from __future__ import annotations

import csv
import json
from collections import Counter

import pytest
from tools import rag2_consensus as rc
from tools import rag2_proposal as rp
from tools.rag2_agreement import expected_rows
from tools.rag2_sample import SAMPLE_CSV

from tests.str.test_rag2_consensus import _decide, _pair

ALL_PDFS = all((rp.ROOT / "corpus/pdf" / f"{d}.pdf").exists() for d in rp._metas())


@pytest.fixture(autouse=True)
def _fake_hash(monkeypatch) -> None:
    monkeypatch.setattr(rc, "compute_content_hash", lambda doc, page, text: text.removeprefix("body-"))


def _pages() -> dict:
    """표본 행은 05 위치 그대로 + 쪽마다 가짜 이웃 하나."""
    pages: dict = {}
    for r in expected_rows():
        pages.setdefault((r["doc_id"], int(r["page"])), [(99, "n" * 64)]).append(
            (int(r["쪽안_청크순번"]), r["chunk_id"])
        )
    return {k: sorted(v) for k, v in pages.items()}


def test_proposal_rows_keep_zero_and_list_neighbours(tmp_path) -> None:
    a, b = _pair(tmp_path)  # 0행 일치 FAN_IN · 1·2·3 불일치 → 결정 FAN_IN · 없음 · FAN_OUT
    decided = _decide(rc.disagreement_rows(*rc.load_pair(a, b)), tmp_path / "d.csv")
    ids = [r["chunk_id"] for r in expected_rows()]
    doc = {"candidates": {"FAN_IN": [{"chunk_id": ids[0], "grade": 2, "db_tagged": True}]},
           "consensus_grades": [{"typology": "FAN_IN", "chunk_id": ids[1], "source": "결정_태그", "grade": 0},
                                {"typology": "FAN_OUT", "chunk_id": ids[3], "source": "결정_태그", "grade": 1}]}  # fmt: skip
    rows = rp.proposal_rows((a, b, decided), doc, _pages())
    got = {r["chunk_id"]: (r["제안태그"], r["출처"], r["이유분류"], r["확인등급"]) for r in rows}
    assert got == {ids[0]: ("FAN_IN", rp.AGREED, "", "FAN_IN=2"),
                   ids[1]: ("FAN_IN", rp.DECIDED, "단순 실수", "FAN_IN=0"),  # 0 은 미확인과 다르게 남음
                   ids[3]: ("FAN_OUT", rp.DECIDED, "단순 실수", "FAN_OUT=1")}  # fmt: skip
    assert all(list(r) == rp.PROPOSAL_FIELDS and r["이웃청크"] == "99=nnnnnnnn" for r in rows)


def test_proposal_stops_on_unchecked_tag(tmp_path) -> None:
    a, b = _pair(tmp_path)
    decided = _decide(rc.disagreement_rows(*rc.load_pair(a, b)), tmp_path / "d.csv")
    with pytest.raises(rp.Unchecked, match="확인 기록이 없는"):
        rp.proposal_rows((a, b, decided), {"candidates": {}}, _pages())


def test_tag_counts_chunk_vs_page_level() -> None:
    rows = [{"chunk_id": "c1", "doc_id": "d", "page": "1", "제안태그": "FAN_IN"}]
    pages = {("d", 1): [(1, "c1"), (2, "c2")], ("d", 2): [(1, "c3")]}
    metas = {"d": {"typology_pages": {"CYCLE": [2]}}}
    c = rp.tag_counts(rows, pages, metas)
    assert c["지금"] == Counter({"무태그": 2, "CYCLE": 1})
    assert c["청크 단위"] == Counter({"FAN_IN": 1, "무태그": 1, "CYCLE": 1})
    assert c["쪽 단위"] == Counter({"FAN_IN": 2, "CYCLE": 1})  # 같은 쪽 이웃 c2 까지


def test_repo_proposal_matches_sample_and_candidates() -> None:
    with rp.PROPOSAL_CSV.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert reader.fieldnames == rp.PROPOSAL_FIELDS and len(rows) == 12
    with SAMPLE_CSV.open(encoding="utf-8", newline="") as f:
        sample = {r["chunk_id"]: r for r in csv.DictReader(f)}
    doc = json.loads(rp.CANDIDATES.read_text(encoding="utf-8"))
    records = {(r["typology"], r["chunk_id"]): r["grade"] for r in doc["consensus_grades"]}
    pairs = set()
    for r in rows:
        assert {k: r[k] for k in rp.POSITION_FIELDS} == {
            k: sample[r["chunk_id"]][k] for k in rp.POSITION_FIELDS
        }
        assert (r["이유분류"] == "") is (r["출처"] == rp.AGREED)
        for tag, cell in zip(r["제안태그"].split(";"), r["확인등급"].split(";"), strict=True):
            key = (rp.SHEET_TO_TYPE[tag], r["chunk_id"])
            assert cell == f"{tag}={records[key]}"
            pairs.add(key)
    assert pairs == set(records)  # 제안 = 확인 ②③ 기록 전부


@pytest.mark.skipif(not ALL_PDFS, reason="corpus/pdf 없음(git 무시 폴더) — 로컬에서 돎")
def test_repo_proposal_neighbours_and_counts() -> None:
    pages, metas = rp.corpus_pages()
    with rp.PROPOSAL_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        want = [f"{p}={c[:8]}" for p, c in pages[(r["doc_id"], int(r["page"]))] if c != r["chunk_id"]]
        assert r["이웃청크"] == ";".join(want)
    c = rp.tag_counts(rows, pages, metas)
    assert [(n, c[n]["FAN_IN"], c[n]["FAN_OUT"], c[n]["무태그"]) for n in c] == [
        ("지금", 19, 6, 657), ("청크 단위", 30, 8, 645), ("쪽 단위", 38, 10, 636)]  # fmt: skip
