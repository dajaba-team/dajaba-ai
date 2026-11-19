"""SCRUM-275-2 정답 확인 시트 — 내보내기·반영 (docs/str/10 "확인 시트"). 가짜 초벌·본문 — DB·LLM 0.

내보내기(범위 (가) CYCLE 전부 + FAN LLM ≥ 1, 초벌지문 칸) · CSV 왕복(BOM·줄바꿈·수식 방지·원래 ' 시작) ·
반영(사람 등급 → 정답, check_scope) · 정답 파일에 본문 없음 · 이미 있는 정답 파일. 점검은 test_rag_answer_sheet_check.
"""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import pytest

from tests.str import rag_answer_sheet as sheet
from tests.str import rag_answer_sheet_support as fx
from tests.str.rag_answer_sheet_check import check
from tests.str.rag_eval_v2_support import expand_answers, unchecked


def test_export_rows_scope_and_order() -> None:
    records = sheet.sheet_records(fx.draft(), fx.TEXTS, fx.FP)
    assert [r["유형"] for r in records] == ["CYCLE", "CYCLE", "CYCLE", "FAN_IN"]  # CYCLE 전부 + FAN_IN LLM≥1
    assert [(r["문서"], r["쪽"], r["쪽안순번"]) for r in records[:3]] == [("doc-a", 3, 1), ("doc-a", 3, 2), ("doc-b", 1, 1)]  # fmt: skip
    assert list(records[0]) == list(sheet.COLUMNS) and {r["초벌지문"] for r in records} == {fx.FP}
    assert all(r["확인등급"] == "" and r["메모"] == "" for r in records)
    assert records[1]["본문"].startswith("'=")  # 수식으로 안 읽게
    assert records[0]["본문"] == "첫 줄\n둘째 줄"


def test_fingerprint_changes_with_either_file() -> None:
    base = sheet.fingerprint(b"d", b"m")
    assert base != sheet.fingerprint(b"d2", b"m") and base != sheet.fingerprint(b"d", b"m2")


def test_csv_round_trip_keeps_formula_and_quote_bodies(tmp_path: Path) -> None:
    texts = {**fx.TEXTS, fx.C3: "'quoted from the start"}
    path = tmp_path / "sheet.csv"
    sheet.write_csv(path, fx.filled(texts=texts))
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    back = sheet.read_csv(path)
    assert back[0]["본문"] == "첫 줄\n둘째 줄" and len(back) == 4 and list(back[0]) == list(sheet.COLUMNS)
    assert check(back, fx.draft(), texts, fx.FP) == []  # 수식 방지 ' · 원래 ' 시작 본문 · 줄바꿈 모두 통과


def test_apply_uses_human_grade_and_records_scope() -> None:
    records = fx.filled({fx.rid("CYCLE", fx.C1): "1", fx.rid("CYCLE", fx.C2): "0"})
    assert check(records, fx.draft(), fx.TEXTS, fx.FP) == []
    out = sheet.build_answers(fx.draft(), records, fx.QUERIES, checker="확인자", checked_at="2026-11-21")
    by_id = {e["query_id"]: e for e in out["queries"]}
    assert set(by_id) == {"H01", "H02", "H03"}  # 정답 없는 질의 빠짐
    cycle = by_id["H01"]
    assert {a["chunk_id"]: a["grade"] for a in cycle["answers"]} == {fx.C1: 1, fx.C3: 1}  # 사람 등급
    assert cycle["check_scope"] == sheet.SCOPE_ALL and cycle["draft"] == "human"
    assert cycle["llm_draft"] == "llm:rag_answer_v1" and cycle["checked_by"] == "확인자"
    assert by_id["H02"]["check_scope"] == sheet.SCOPE_POSITIVE
    assert by_id["H03"]["answers"] == [] and by_id["H03"]["check_scope"] == sheet.SCOPE_POSITIVE
    assert unchecked(out) == []


def test_answers_have_no_body_text() -> None:
    out = sheet.build_answers(fx.draft(), fx.filled(), fx.QUERIES, checker="x", checked_at="2026-11-21")
    dumped = json.dumps(out, ensure_ascii=False)
    for body in fx.TEXTS.values():
        assert body not in dumped and body.split()[0] not in dumped


def test_existing_answers_policy() -> None:
    draft = fx.draft()
    assert sheet.existing_problem(None, draft, fx.QUERIES) is None
    fresh = expand_answers(draft, fx.QUERIES)
    assert sheet.existing_problem(fresh, draft, fx.QUERIES) is None  # 확인 전 · 같은 초벌 → 대체
    checked = sheet.build_answers(draft, fx.filled(), fx.QUERIES, checker="x", checked_at="2026-11-21")
    assert "이미 확인" in (sheet.existing_problem(checked, draft, fx.QUERIES) or "")
    other = copy.deepcopy(fresh)
    other["queries"][0]["answers"] = []
    assert "초벌" in (sheet.existing_problem(other, draft, fx.QUERIES) or "")


def test_guide_has_grades_and_no_positions() -> None:
    assert all(g in sheet.GUIDE_MD for g in ("2", "1", "0")) and "확인등급" in sheet.GUIDE_MD
    assert "doc-" not in sheet.GUIDE_MD  # 위치·예시 없음(공통 기준과 같은 원칙)


def _raw_csv(tmp_path: Path, header: list[str], rows: list[list[str]]) -> Path:
    path = tmp_path / "raw.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _rows() -> list[list[str]]:
    return [[str(r[c] if r[c] is not None else "") for c in sheet.COLUMNS] for r in fx.filled()]


@pytest.mark.parametrize("column", ["확인등급", "본문"])
def test_duplicate_column_is_rejected(tmp_path: Path, column: str) -> None:
    """같은 이름 칸이 둘이면 DictReader 는 뒤 칸만 남김 — 앞 칸의 빈 등급·다른 본문이 숨지 않게 머리글부터 거절."""
    header = [*sheet.COLUMNS, column]
    rows = [[*r, r[sheet.COLUMNS.index(column)]] for r in _rows()]
    with pytest.raises(sheet.SheetFormatError) as exc:
        sheet.read_csv(_raw_csv(tmp_path, header, rows))
    assert exc.value.problems[0][0] == 1


@pytest.mark.parametrize(
    "header", [list(sheet.COLUMNS[:-1]), list(reversed(sheet.COLUMNS)), [*sheet.COLUMNS, "추가"]]
)
def test_missing_reordered_or_extra_column_is_rejected(tmp_path: Path, header: list[str]) -> None:
    with pytest.raises(sheet.SheetFormatError):
        sheet.read_csv(_raw_csv(tmp_path, header, []))


def test_row_with_wrong_cell_count_is_rejected(tmp_path: Path) -> None:
    rows = _rows()
    rows[1] = [*rows[1], "넘친 칸"]
    rows[2] = rows[2][:-1]
    with pytest.raises(sheet.SheetFormatError) as exc:
        sheet.read_csv(_raw_csv(tmp_path, list(sheet.COLUMNS), rows))
    assert [row for row, _ in exc.value.problems] == [3, 4]
