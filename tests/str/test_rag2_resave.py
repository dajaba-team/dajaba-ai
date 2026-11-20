"""SCRUM-306 추가 검토 3회차 회귀 — 정상 재저장(셀 안 줄바꿈)은 통과 · 블라인드 폴더 검사는 대소문자 무시."""

from __future__ import annotations

import pytest
from tools import rag2_agreement as ag
from tools import rag2_consensus as rc
from tools import rag2_io

from tests.str.test_rag2_agreement import evidence_in, write_sheet
from tests.str.test_rag2_consensus import _decide


@pytest.fixture(autouse=True)
def _fake_hash(monkeypatch) -> None:
    monkeypatch.setattr(rc, "compute_content_hash", lambda doc, page, text: text.removeprefix("body-"))


def test_decision_sheet_resaved_with_lf_passes_but_changed_evidence_fails(tmp_path) -> None:
    """3회차 — 결정 시트에 복사된 A·B 근거위치: 셀 안 줄바꿈(CRLF→LF)만 바뀌면 통과, 문장 번호가 바뀌면 거절."""
    rows = ag.expected_rows()
    two = f"{evidence_in(rows[1])};\r\n{evidence_in(rows[1])}"
    a = write_sheet(
        tmp_path / "a.csv", {1: "FAN_IN"}, rows=lambda r: [r[0], {**r[1], "근거위치": two}, *r[2:]]
    )
    b = write_sheet(tmp_path / "b.csv", {0: "FAN_IN"})
    listed = rc.disagreement_rows(*rc.load_pair(a, b))
    assert "\r\n" in listed[1]["A_근거위치"]
    resaved = [{**r, "A_근거위치": r["A_근거위치"].replace("\r\n", "\n")} for r in listed]
    rc.load_decisions(_decide(resaved, tmp_path / "ok.csv", {}), listed)
    first = ag.RANGE_CELL.fullmatch(rows[1]["문장범위"])[1]
    changed = [
        resaved[0],
        {**resaved[1], "A_근거위치": resaved[1]["A_근거위치"].replace(f"s{first}", f"s{int(first) + 1}", 1)},
    ]
    with pytest.raises(ag.SheetError, match="A_근거위치"):
        rc.load_decisions(_decide(changed, tmp_path / "bad.csv", {}), listed)


def test_blind_check_ignores_case(tmp_path) -> None:
    """macOS 는 `BLIND_A` 와 `blind_A` 가 같은 폴더 — 둘 다(그리고 새 `Blind_*`) 거절."""
    (tmp_path / "blind_A").mkdir()
    for given in ("blind_A/checker", "BLIND_A/checker", "Blind_new/checker"):
        assert "블라인드" in (rag2_io.out_dir_problem(tmp_path / given, set()) or ""), given
