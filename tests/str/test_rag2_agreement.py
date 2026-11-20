"""SCRUM-306 일치율 — 받은 시트 거절 · κ 손 계산 · 적은 붙임 κ 비움 (03 5절)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from tools import rag2_agreement as ag
from tools.rag2_blind import SHEET_FIELDS


def evidence_in(row: dict[str, str]) -> str:
    """그 행 쪽 · 문장범위 첫 문장 — 근거위치 검사를 통과하는 값."""
    return f"p{row['page']} s{ag.RANGE_CELL.fullmatch(row['문장범위'])[1]}"


def write_sheet(path: Path, tags: dict[int, str] | None = None, **edit) -> Path:
    """기대 행 80 + 태그(기본 `없음`). edit: rows=행 목록 바꾸는 함수, fields=칸 이름, encoding."""
    rows = [{**r, "태그": "없음", "근거위치": "", "메모": ""} for r in ag.expected_rows()]
    for i, cell in (tags or {}).items():
        rows[i].update({"태그": cell, "근거위치": evidence_in(rows[i])})
    rows = edit.get("rows", lambda x: x)(rows)
    fields = edit.get("fields", SHEET_FIELDS)
    with path.open("w", encoding=edit.get("encoding", "utf-8"), newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_kappa_hand_example() -> None:
    a = [True, True, True] + [False] * 7
    b = [True, True, False, True] + [False] * 6
    p_o, p_e, k = ag.kappa(a, b)
    assert p_o == pytest.approx(0.8)  # 8/10 같은 답
    assert p_e == pytest.approx(0.3 * 0.3 + 0.7 * 0.7)  # 0.58
    assert k == pytest.approx((0.8 - 0.58) / (1 - 0.58))  # 0.5238
    assert ag.kappa([True, False], [True, False])[2] == pytest.approx(1.0)
    assert ag.kappa([True, False], [False, True])[2] == pytest.approx(-1.0)


def test_kappa_undefined_when_chance_is_one() -> None:
    assert ag.kappa([False] * 5, [False] * 5) == (1.0, 1.0, None)
    with pytest.raises(ValueError):
        ag.kappa([], [])


def test_parse_tags_rules() -> None:
    assert ag.parse_tags("없음") == frozenset()
    assert ag.parse_tags(" FAN_IN ; GS ") == {"FAN_IN", "GS"}
    for bad, msg in [("", "빈 칸"), ("FAN_IN;", "빈 칸"), ("FANIN", "모르는"), ("SCATTER_GATHER", "모르는"),
                     ("없음;CYCLE", "없음"), ("SG;SG", "두 번")]:  # fmt: skip
        with pytest.raises(ValueError, match=msg):
            ag.parse_tags(bad)


def test_valid_sheet_loads_with_bom_and_crlf(tmp_path) -> None:
    rows = ag.load_sheet(write_sheet(tmp_path / "a.csv", {0: "FAN_IN;GS"}, encoding="utf-8-sig"))
    assert len(rows) == 80 and rows[0].tags == {"FAN_IN", "GS"} and rows[1].tags == frozenset()


@pytest.mark.parametrize(
    ("edit", "msg"),
    [
        ({"rows": lambda r: r[:-1]}, "행 수"),
        ({"rows": lambda r: r + [r[0]]}, "행 수"),
        ({"rows": lambda r: [r[1], r[0], *r[2:]]}, "순서"),
        ({"rows": lambda r: [r[0], r[0], *r[2:]]}, "중복"),
        ({"rows": lambda r: [{**r[0], "시작": "0"}, *r[1:]]}, "다름"),
        ({"rows": lambda r: [{**r[0], "문장범위": "s1~s2"}, *r[1:]]}, "다름"),
        ({"rows": lambda r: [{**r[0], "태그": ""}, *r[1:]]}, "빈 칸"),
        ({"rows": lambda r: [{**r[0], "태그": "FUNNEL"}, *r[1:]]}, "모르는"),
        ({"rows": lambda r: [{**r[0], "태그": "없음;FAN_IN", "근거위치": "p1 s1"}, *r[1:]]}, "없음"),
        ({"rows": lambda r: [{**r[0], "태그": "CYCLE"}, *r[1:]]}, "근거위치"),
        ({"fields": [*SHEET_FIELDS[:-1], "비고"]}, "칸이 다름"),
        ({"fields": [SHEET_FIELDS[1], SHEET_FIELDS[0], *SHEET_FIELDS[2:]]}, "칸이 다름"),
        ({"encoding": "cp949", "rows": lambda r: [{**r[0], "메모": "한글"}, *r[1:]]}, "UTF-8"),
    ],
)
def test_sheet_rejected(tmp_path, edit, msg) -> None:
    with pytest.raises(ag.SheetError, match=msg):
        ag.load_sheet(write_sheet(tmp_path / "a.csv", **edit))


def test_agreement_counts_and_few_tag_rule(tmp_path) -> None:
    a = ag.load_sheet(write_sheet(tmp_path / "a.csv", {i: "FAN_IN" for i in range(6)} | {10: "CYCLE"}))
    b = ag.load_sheet(write_sheet(tmp_path / "b.csv", {i: "FAN_IN" for i in range(1, 7)} | {11: "CYCLE"}))
    res = ag.agreement(a, b)
    fan = res["FAN_IN"]
    assert (fan["tagged_a"], fan["tagged_b"]) == (6, 6)
    assert fan["p_o"] == pytest.approx(78 / 80)
    p = 6 / 80
    p_e = p * p + (1 - p) * (1 - p)
    assert fan["kappa"] == pytest.approx((78 / 80 - p_e) / (1 - p_e))
    assert res["CYCLE"]["kappa"] is None and res["CYCLE"]["kappa_raw"] is not None  # 붙임 1 < 5
    assert res["SG"]["kappa"] is None and res["SG"]["kappa_raw"] is None  # 아무도 안 붙임 — p_e = 1
    anyk = res[ag.ANY_KEY]
    assert (anyk["tagged_a"], anyk["tagged_b"]) == (7, 7) and anyk["kappa"] is not None


def test_agreement_rejects_different_order() -> None:
    x = [ag.Tagged("a", frozenset(), ""), ag.Tagged("b", frozenset(), "")]
    with pytest.raises(ag.SheetError, match="순서"):
        ag.agreement(x, x[::-1])


def _shift(rows: list[dict], src: int, dst: int) -> list[dict]:
    """src 행의 태그·근거위치를 dst 행으로 옮김(열만 이동한 시트)."""
    moved = [dict(r) for r in rows]
    moved[dst].update({"태그": rows[src]["태그"], "근거위치": rows[src]["근거위치"]})
    moved[src].update({"태그": "없음", "근거위치": ""})
    return moved


def test_moved_tag_with_evidence_is_rejected(tmp_path) -> None:
    rows = ag.expected_rows()
    dst = next(i for i, r in enumerate(rows) if r["page"] != rows[0]["page"])
    with pytest.raises(ag.SheetError, match="쪽"):
        ag.load_sheet(write_sheet(tmp_path / "a.csv", {0: "FAN_IN"}, rows=lambda r: _shift(r, 0, dst)))


@pytest.mark.parametrize(
    ("evidence", "msg"),
    [
        ("p{page} s999", "문장범위 밖"),
        ("p{other} s{lo}", "쪽"),
        ("{page}쪽 {lo}번", "꼴"),
        ("p{page} s{lo};", "꼴"),
    ],
)
def test_evidence_must_sit_inside_its_row(tmp_path, evidence, msg) -> None:
    row = ag.expected_rows()[0]
    cell = evidence.format(
        page=row["page"], other=int(row["page"]) + 1, lo=ag.RANGE_CELL.fullmatch(row["문장범위"])[1]
    )
    for tag in ("FAN_IN", "없음"):  # 없음 행에 적힌 근거도 같은 검사
        edit = {"rows": lambda r, t=tag: [{**r[0], "태그": t, "근거위치": cell}, *r[1:]]}
        with pytest.raises(ag.SheetError, match=msg):
            ag.load_sheet(write_sheet(tmp_path / f"{tag}.csv", **edit))


def test_extra_cell_from_comma_is_rejected(tmp_path) -> None:
    """`FAN_IN,GS` 처럼 쉼표로 칸이 밀린 행 — 셀 수 ≠ 머리글이면 거절(남는 셀을 버리지 않음)."""
    path = write_sheet(tmp_path / "a.csv", {0: "FAN_IN"})
    raw = path.read_bytes().decode("utf-8")
    path.write_bytes(raw.replace(",FAN_IN,", ",FAN_IN,GS,", 1).encode("utf-8"))
    with pytest.raises(ag.SheetError, match="셀 11 ≠ 머리글 10"):
        ag.load_sheet(path)
