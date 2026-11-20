"""SCRUM-306 확인 ③ — 결정태그 중 후보 밖 (유형, 청크)만 · 행ID D- · 결정 시트 검사 통과해야 · 덮지 않음."""

from __future__ import annotations

import pytest
from tools import rag2_consensus as rc
from tools.rag2_agreement import SheetError, expected_rows

from tests.str import rag_calibration_sheet as cal
from tests.str import rag_eval_v3_decided as dc
from tests.str import rag_eval_v3_round2 as r2
from tests.str.test_rag2_consensus import _decide, _pair
from tests.str.test_rag_eval_v3_round2 import _db, _read


@pytest.fixture(autouse=True)
def _fake_hash(monkeypatch) -> None:
    fake = lambda doc, page, text: text.removeprefix("body-")  # noqa: E731 — `body-<chunk_id>` = 그 청크 본문
    monkeypatch.setattr(r2, "compute_content_hash", fake)
    monkeypatch.setattr(rc, "compute_content_hash", fake)


def test_decided_sheet_lists_only_new_type_chunk(tmp_path) -> None:
    a, b = _pair(tmp_path)
    decided = _decide(
        rc.disagreement_rows(*rc.load_pair(a, b)), tmp_path / "d.csv"
    )  # FAN_IN · 없음 · FAN_OUT
    ids = [r["chunk_id"] for r in expected_rows()]
    have = {"FAN_IN": [{"chunk_id": ids[1]}]}  # 1행 FAN_IN 은 이미 후보 → 빠짐
    msgs: list[str] = []
    assert dc.export((a, b, decided), tmp_path / "c", have, _db, msgs.append) == 0
    rows = _read(tmp_path / "c" / dc.DECIDED_SHEET)
    assert list(rows[0]) == cal.COLUMNS
    assert [(r["행"], r["유형"], r["chunk_id"], r["확인등급"]) for r in rows] == [
        ("D-FO-001", "FAN_OUT", ids[3], f"FO-{ids[3][:8]}=")]  # fmt: skip
    assert msgs == [f"decided_new=1 FAN_OUT=1 → {dc.DECIDED_SHEET}"]
    assert dc.export((a, b, decided), tmp_path / "c", have, _db, lambda _m: None) == 1  # 덮지 않음


def test_decided_sheet_refuses_unfilled_decisions(tmp_path) -> None:
    a, b = _pair(tmp_path)
    listed = rc.disagreement_rows(*rc.load_pair(a, b))
    decided = _decide(listed, tmp_path / "d.csv", {0: {"이유분류": ""}})
    with pytest.raises(SheetError, match="이유분류"):
        dc.export((a, b, decided), tmp_path / "c", {}, _db, lambda _m: None)
    assert not (tmp_path / "c").exists()
