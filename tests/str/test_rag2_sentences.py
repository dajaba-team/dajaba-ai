"""SCRUM-306 문장범위·범위 보기 — 03 3절 문장 나누기 규칙 · (중간) 표시 · [s번호] 줄."""

from __future__ import annotations

import json

import pytest
from tools.rag2_agreement import RANGES_FIXTURE
from tools.rag2_blind import load_metas, load_sample
from tools.rag2_sample import read_pages, sample_pdfs_present
from tools.rag2_show_chunk import MID_MARK, chunk_lines, sentence_range, sentence_spans

TEXT = "One two. Three?  Four!\nFive\n\n \nSix 다. Seven"


def _words(text: str) -> list[str]:
    return [text[s:e] for s, e in sentence_spans(text)]


def test_spans_split_on_end_mark_plus_space_and_blank_line() -> None:
    assert _words(TEXT) == ["One two.", "Three?", "Four!", "Five", "Six 다.", "Seven"]  # 줄바꿈도 공백


def test_spans_skip_blank_pieces_and_trim() -> None:
    assert _words("  \n\n  A.  \n\n\n  B  ") == ["A.", "B"]
    assert sentence_spans("") == [] and sentence_spans(" \n\n ") == []


def test_no_split_without_space_after_mark() -> None:
    assert _words("v1.2 and e.g.x end.") == ["v1.2 and e.g.x end."]


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (0, len("One two."), "s1~s1"),  # 한 문장 꼭 맞음
        (0, len(TEXT), "s1~s6"),
        (4, 15, "s1(중간)~s2"),  # two. Three?
        (10, 12, "s2(중간)~s2(중간)"),  # 한 문장 안
        (9, 12, "s2~s2(중간)"),  # 문장 첫 글자에서 시작
        (9, 20, "s2~s3(중간)"),
        (7, 9, "s1(중간)~s1"),  # 끝의 마침표 + 공백 — 다음 문장은 안 걸림
    ],
)
def test_range_marks_mid(start: int, end: int, expected: str) -> None:
    assert sentence_range(sentence_spans(TEXT), start, end) == expected


def test_range_ignores_gap_between_sentences() -> None:
    spans = sentence_spans("A.   B.")
    assert sentence_range(spans, 1, 5) == "s1(중간)~s1"  # 공백에서 끝 — 다음 문장 안 걸림
    assert sentence_range(spans, 2, 7) == "s2~s2"  # 공백에서 시작 — 앞 문장 안 걸림


def test_range_without_sentence_fails() -> None:
    with pytest.raises(ValueError, match="문장이 없음"):
        sentence_range(sentence_spans("A.   B."), 2, 5)


def test_chunk_lines_label_each_sentence() -> None:
    assert chunk_lines(TEXT, 4, 20) == ["[s1(중간)] two.", "[s2] Three?", "[s3(중간)] Fou"]
    assert chunk_lines(TEXT, 9, 15) == ["[s2] Three?"]
    assert chunk_lines("ａ b. c", 0, 4) == ["[s1] a b."]  # NFKC
    with pytest.raises(ValueError, match="범위"):
        chunk_lines(TEXT, 5, 999)


def _pick_rows() -> list[dict[str, str]]:
    """문장범위 모양별 하나씩 — 시작만 (중간) · 끝만 (중간) · 표시 없음."""
    fixed = json.loads(RANGES_FIXTURE.read_text(encoding="utf-8"))["ranges"]
    rows = [{**r, "range": fixed[r["chunk_id"]]} for r in load_sample()]
    shapes = [lambda v: v.split("~")[0].endswith(MID_MARK) and not v.endswith(MID_MARK),
              lambda v: v.endswith(MID_MARK) and not v.split("~")[0].endswith(MID_MARK),
              lambda v: MID_MARK not in v]  # fmt: skip
    return [next(r for r in rows if shape(r["range"])) for shape in shapes]


@pytest.mark.skipif(not sample_pdfs_present(), reason="corpus/pdf 없음(git 무시 폴더) — 로컬에서 돎")
def test_viewer_first_last_label_equals_sheet_range_on_3_rows() -> None:
    metas = load_metas()
    for r in _pick_rows():
        page = read_pages(metas[r["doc_id"]])[int(r["page"]) - 1]
        lines = chunk_lines(page, int(r["시작"]), int(r["끝"]))
        first, last = (line[1 : line.index("]")] for line in (lines[0], lines[-1]))
        assert f"{first}~{last}" == r["range"]
