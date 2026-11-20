"""SCRUM-306 불일치 목록 · 결정 반영 · 합의 · AI 대 합의 (03 5·6절) — 이름 A/B · 메모·본문 0."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from tools import rag2_consensus as rc
from tools.rag2_agreement import SheetError, Tagged, load_sheet
from tools.rag2_sample import ROOT

from tests.str.test_rag2_agreement import write_sheet

A_TAGS = {0: "FAN_IN", 1: "FAN_IN;GS", 2: "CYCLE"}
B_TAGS = {0: "FAN_IN", 1: "FAN_IN", 3: "FAN_OUT"}  # 1·2·3 행이 다름


@pytest.fixture(autouse=True)
def _fake_hash(monkeypatch) -> None:
    """결정 시트 본문 해시 — 단위 테스트는 `body-<chunk_id>` 를 그 청크 본문으로 봄."""
    monkeypatch.setattr(rc, "compute_content_hash", lambda doc, page, text: text.removeprefix("body-"))


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    a = write_sheet(tmp_path / "a.csv", A_TAGS, rows=lambda r: [{**r[0], "메모": "SECRET-MEMO-A"}, *r[1:]])
    return a, write_sheet(tmp_path / "b.csv", B_TAGS)


def _decide(listed: list[dict[str, str]], path: Path, override: dict[int, dict] | None = None) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rc.DISAGREE_FIELDS, lineterminator="\n")
        writer.writeheader()
        for i, r in enumerate(listed):
            row = {
                **r,
                rc.TEXT_FIELD: f"body-{r['chunk_id']}",
                "결정태그": ["FAN_IN", "없음", "FAN_OUT"][i],
                "근거줄": "00 조건 1",
                "이유분류": "단순 실수",
            }
            writer.writerow({**row, **(override or {}).get(i, {})})
    return path


def test_disagreement_lists_only_split_rows_with_a_b(tmp_path) -> None:
    a, b = rc.load_pair(*_pair(tmp_path))
    listed = rc.disagreement_rows(a, b)
    assert [r["A_태그"] for r in listed] == ["FAN_IN;GS", "CYCLE", "없음"]
    assert [r["B_태그"] for r in listed] == ["FAN_IN", "없음", "FAN_OUT"]
    assert all(r[k] == "" for r in listed for k in rc.DECISION_FIELDS)
    assert all(r[rc.TEXT_FIELD] == "" for r in listed)  # 본문은 해시 대조 뒤 넘길 때만
    out = tmp_path / "out" / "disagree.csv"
    out.parent.mkdir()
    with pytest.raises(ValueError, match="본문 빈 행"):
        rc.write_disagreement(listed, out)
    texts = {r["chunk_id"]: f"body {i}" for i, r in enumerate(listed)}
    rc.write_disagreement(rc.disagreement_rows(a, b, texts), out)
    text = out.read_text(encoding="utf-8-sig")
    assert "body 0" in text
    assert "SECRET-MEMO" not in text and "메모" not in text
    assert "준영" not in text and text.splitlines()[0] == ",".join(rc.DISAGREE_FIELDS)


def test_disagreement_refuses_repo_path_and_overwrite(tmp_path) -> None:
    with pytest.raises(ValueError, match="리포 밖"):
        rc.write_disagreement([], ROOT / "disagree_should_not_exist.csv")
    assert not (ROOT / "disagree_should_not_exist.csv").exists()
    (tmp_path / "d.csv").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="덮지 않음"):
        rc.write_disagreement([], tmp_path / "d.csv")


def test_identical_files_rejected(tmp_path) -> None:
    a = write_sheet(tmp_path / "a.csv", A_TAGS)
    with pytest.raises(SheetError, match="같음"):
        rc.load_pair(a, write_sheet(tmp_path / "b.csv", A_TAGS))


def test_consensus_uses_agreed_rows_and_decisions(tmp_path) -> None:
    a, b = rc.load_pair(*_pair(tmp_path))
    listed = rc.disagreement_rows(a, b)
    agreed = rc.consensus(a, b, rc.load_decisions(_decide(listed, tmp_path / "d.csv"), listed))
    ids = [x.chunk_id for x in a]
    assert agreed[ids[0]] == {"FAN_IN"}  # 일치
    assert (agreed[ids[1]], agreed[ids[2]], agreed[ids[3]]) == ({"FAN_IN"}, frozenset(), {"FAN_OUT"})
    assert sum(bool(t) for t in agreed.values()) == 3


@pytest.mark.parametrize(
    ("override", "msg"),
    [
        ({0: {"결정태그": ""}}, "결정태그"),
        ({0: {"결정태그": "FUNNEL"}}, "결정태그"),
        ({1: {"근거줄": " "}}, "근거줄"),
        ({2: {"이유분류": "모름"}}, "이유분류"),
        ({0: {"A_태그": "CYCLE"}}, "다름"),
        ({0: {"chunk_id": "f" * 64}}, "다름"),
    ],
)
def test_decisions_rejected(tmp_path, override, msg) -> None:
    a, b = rc.load_pair(*_pair(tmp_path))
    listed = rc.disagreement_rows(a, b)
    with pytest.raises(SheetError, match=msg):
        rc.load_decisions(_decide(listed, tmp_path / "d.csv", override), listed)


def test_consensus_rejects_missing_decision() -> None:
    a = [Tagged("x", frozenset({"CYCLE"}), "p1 s1"), Tagged("y", frozenset(), "")]
    b = [Tagged("x", frozenset(), ""), Tagged("y", frozenset(), "")]
    with pytest.raises(SheetError, match="결정한 행"):
        rc.consensus(a, b, {})
    with pytest.raises(SheetError, match="결정한 행"):
        rc.consensus(a, b, {"x": frozenset(), "y": frozenset()})


def test_ai_vs_consensus_hand_example() -> None:
    agreed = {
        "a": frozenset({"FAN_IN"}),
        "b": frozenset({"FAN_IN"}),
        "c": frozenset(),
        "d": frozenset({"CYCLE"}),
    }
    ai = {
        "a": frozenset({"FAN_IN"}),
        "b": frozenset(),
        "c": frozenset({"FAN_IN"}),
        "d": frozenset(),
        "z": frozenset(),
    }
    res = rc.ai_vs_consensus(agreed, ai)
    fan = res["FAN_IN"]
    assert (fan["tp"], fan["fp"], fan["fn"], fan["tn"]) == (1, 1, 1, 1)
    assert (fan["missed"], fan["wrong"], fan["p_o"]) == (1, 1, 0.5)
    assert fan["kappa"] == pytest.approx(0.0)  # p_o 0.5 = p_e 0.5
    assert (res["CYCLE"]["missed"], res["CYCLE"]["wrong"]) == (1, 0)
    assert (res["후보유무"]["tp"], res["후보유무"]["fn"], res["후보유무"]["fp"]) == (
        1,
        2,
        1,
    )  # 정답 a·b·d · AI a·c


def test_ai_candidates_read_from_02() -> None:
    ai = rc.ai_candidates()
    assert len(ai) == 398 and sum(bool(t) for t in ai.values()) == 16
    assert set().union(*ai.values()) == {"FAN_IN", "FAN_OUT", "CYCLE", "GS"}


def test_identical_content_rejected_even_with_bom(tmp_path) -> None:
    """같은 사람 시트를 BOM 만 붙여 다시 저장한 사본 — 바이트는 달라도 태그·근거·메모가 같으면 거절."""
    a = write_sheet(tmp_path / "a.csv", A_TAGS)
    b = write_sheet(tmp_path / "b.csv", A_TAGS, encoding="utf-8-sig")
    assert a.read_bytes() != b.read_bytes()
    with pytest.raises(SheetError, match="같음"):
        rc.load_pair(a, b)
    rc.load_pair(
        a, write_sheet(tmp_path / "c.csv", A_TAGS, rows=lambda r: [{**r[0], "메모": "다른 메모"}, *r[1:]])
    )


def test_decision_body_must_hash_to_chunk(tmp_path) -> None:
    a, b = rc.load_pair(*_pair(tmp_path))
    listed = rc.disagreement_rows(a, b)
    other = listed[1]["chunk_id"]
    with pytest.raises(SheetError, match="본문 해시"):
        rc.load_decisions(_decide(listed, tmp_path / "d.csv", {0: {rc.TEXT_FIELD: f"body-{other}"}}), listed)
    ok = _decide(listed, tmp_path / "e.csv", {0: {rc.TEXT_FIELD: f"'body-{listed[0]['chunk_id']}"}})
    rc.load_decisions(ok, listed)  # 엑셀 앞 작은따옴표는 풀고 봄


def test_agreement_groups_split_old_and_new(tmp_path) -> None:
    rows = rc.expected_rows()
    new_idx = [i for i, r in enumerate(rows) if r["doc_id"] in rc.NEW_DOCS]
    old0 = next(i for i in range(len(rows)) if i not in new_idx)
    a = load_sheet(write_sheet(tmp_path / "a.csv", {new_idx[0]: "CYCLE", old0: "FAN_IN"}))
    b = load_sheet(write_sheet(tmp_path / "b.csv", {new_idx[0]: "CYCLE"}))
    res = rc.agreement_groups(a, b)
    assert len(new_idx) == 10 and set(res) == {"전체", "기존", "새3문서"}
    assert res["새3문서"]["CYCLE"]["tagged_a"] == 1 and res["새3문서"]["CYCLE"]["p_o"] == 1.0
    assert res["기존"]["FAN_IN"]["tagged_a"] == 1 and res["기존"]["FAN_IN"]["p_o"] == pytest.approx(69 / 70)
    assert res["전체"]["FAN_IN"]["p_o"] == pytest.approx(79 / 80)


def test_ai_vs_consensus_skips_rows_without_ai_candidates() -> None:
    agreed = {"a": frozenset({"FAN_IN"}), "new": frozenset({"CYCLE"})}
    res = rc.ai_vs_consensus(agreed, {"a": frozenset({"FAN_IN"})})
    assert res["CYCLE"]["fn"] == 0 and res["FAN_IN"]["tp"] == 1  # 새 문서 행은 안 셈
