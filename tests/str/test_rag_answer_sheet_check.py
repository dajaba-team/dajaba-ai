"""SCRUM-275-2 시트 점검 (추가 검토 1 반영) — 초벌 완전성 · 확인 시트 대조. 가짜 초벌·본문 — DB·LLM 0.

확인 안 한 행·다른 본문·다른 초벌 위의 시트가 정답으로 들어가지 않는지.
"""

from __future__ import annotations

import pytest

from tests.str import rag_answer_sheet_check as chk
from tests.str import rag_answer_sheet_support as fx
from tests.str.rag_answer_sheet_check import SheetError, body_matches, check, draft_problems, summarize


def _errors(records: list[dict], texts: dict | None = None, fp: str = fx.FP) -> list[SheetError]:
    return check(records, fx.draft(), texts or fx.TEXTS, fp)


def _kinds_at(errors: list[SheetError], row: int) -> set[str]:
    return {e.kind for e in errors if e.row == row}


def test_complete_draft_passes() -> None:
    assert draft_problems(fx.draft(), fx.DB) == []


def test_limit_draft_is_rejected() -> None:
    assert any("limit" in p for p in draft_problems({**fx.draft(), "limit": 1}, fx.DB))


@pytest.mark.parametrize("graded", [None, {}, {"CYCLE": []}])
def test_missing_or_empty_graded_is_rejected(graded: object) -> None:
    draft = {**fx.draft(), "graded_by_typology": graded}
    assert draft_problems(draft, fx.DB) != []


def test_partial_draft_is_rejected() -> None:
    draft = fx.draft()
    draft["graded_by_typology"]["CYCLE"] = draft["graded_by_typology"]["CYCLE"][:1]  # 일부 청크만 매김
    assert any("CYCLE" in p and "집합" in p for p in draft_problems(draft, fx.DB))


def test_duplicate_bad_grade_and_moved_chunks_are_rejected() -> None:
    draft = fx.draft()
    cycle = draft["graded_by_typology"]["CYCLE"]
    cycle.append(dict(cycle[0]))
    draft["graded_by_typology"]["FAN_IN"][0]["grade"] = 3
    problems = draft_problems(draft, {**fx.DB, fx.C3: ("doc-b", 9)})
    assert any("두 번" in p for p in problems) and any("등급" in p for p in problems)
    assert any("위치" in p for p in problems)
    assert any("행 수" in p for p in draft_problems(fx.draft(), {**fx.DB, "c9" * 32: ("doc-z", 1)}))


def test_partial_sheet_is_rejected() -> None:
    missing = [e for e in _errors(fx.filled()[:2]) if e.kind == chk.MISSING]
    assert len(missing) == 2 and all(e.row is None for e in missing)


@pytest.mark.parametrize(("bad", "kind"), [("", chk.BLANK), ("3", chk.BAD_GRADE), ("1.5", chk.BAD_GRADE),
                                           ("two", chk.BAD_GRADE), ("-1", chk.BAD_GRADE)])  # fmt: skip
def test_bad_grade_is_rejected_with_row_number(bad: str, kind: str) -> None:
    records = fx.filled()
    records[0]["확인등급"] = bad
    assert _kinds_at(_errors(records), 2) == {kind}


@pytest.mark.parametrize(("column", "value", "kind"), [
    ("chunk_id", "ff" * 32, chk.IDENTITY), ("LLM등급", "0", chk.IDENTITY), ("유형", "FAN_IN", chk.POSITION),
    ("문서", "doc-z", chk.POSITION), ("쪽", "9", chk.POSITION), ("쪽안순번", "7", chk.POSITION),
    ("초벌지문", "00:11", chk.FINGERPRINT),
])  # fmt: skip
def test_mismatched_cells_are_rejected(column: str, value: str, kind: str) -> None:
    records = fx.filled()
    records[1][column] = value
    assert _kinds_at(_errors(records), 3) == {kind}


def test_swapped_bodies_are_rejected() -> None:
    records = fx.filled()
    records[0]["본문"], records[2]["본문"] = records[2]["본문"], records[0]["본문"]
    errors = _errors(records)
    assert _kinds_at(errors, 2) == {chk.BODY} and _kinds_at(errors, 4) == {chk.BODY}
    assert all("첫 줄" not in str(e) for e in errors)  # 오류에 본문 없음


def test_other_draft_or_corpus_fingerprint_is_rejected() -> None:
    errors = _errors(fx.filled(), fp="00" * 8 + ":" + "11" * 8)
    assert {e.kind for e in errors} == {chk.FINGERPRINT} and len(errors) == 4


def test_duplicate_and_extra_rows_are_rejected() -> None:
    records = fx.filled()
    extra = dict(records[0], row_id=fx.rid("FAN_OUT", fx.C1), 유형="FAN_OUT")
    errors = _errors([*records, dict(records[0]), extra])
    assert _kinds_at(errors, 6) == {chk.DUPLICATE} and _kinds_at(errors, 7) == {chk.UNKNOWN}


def test_row_id_text_cannot_fake_kind() -> None:
    """row_id 를 "확인등급 빈 칸"으로 둔 없는 행 → 초벌에 없는 행(종류는 글자 검색이 아니라 구조)."""
    errors = _errors([*fx.filled(), dict(fx.filled()[0], row_id=chk.BLANK)])
    assert [e.kind for e in errors] == [chk.UNKNOWN] and summarize(errors) == {
        chk.UNKNOWN: [f"행 6 ({chk.BLANK})"]
    }


@pytest.mark.parametrize(
    ("sheet_text", "original", "ok"),
    [
        ("'=SUM(A1)", "=SUM(A1)", True),  # 수식 방지로 붙인 '
        ("'quoted", "'quoted", True),  # 원래 ' 로 시작
        ("quoted", "'quoted", False),  # 원래 ' 를 시트가 먹음 → 다른 글
        ("line1\r\nline2  ", "line1\nline2", True),  # CRLF·끝 공백
        ("''=x", "=x", False),  # ' 는 하나만 뗌
        ("other body", "plain english body", False),
    ],
)
def test_body_normalization(sheet_text: str, original: str, ok: bool) -> None:
    assert body_matches(sheet_text, original) is ok


def test_summarize_groups_by_kind() -> None:
    records = fx.filled()
    records[0]["확인등급"] = ""
    records[1]["쪽"] = "9"
    records[2]["본문"] = "다른 글"
    groups = summarize(_errors(records[:3]))
    assert groups[chk.BLANK] == [f"행 2 ({records[0]['row_id']})"]
    assert len(groups[chk.POSITION]) == 1 and len(groups[chk.BODY]) == 1 and len(groups[chk.MISSING]) == 1
