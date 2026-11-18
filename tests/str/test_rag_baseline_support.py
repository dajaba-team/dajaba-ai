"""SCRUM-146 — 기준선 하네스 순수 도우미 (docs/str/10 "기준선"). LLM·DB 0.

청크 위치 = doc_id · page · 쪽 안 순번(적재 순서) · lang — 원문 지문 없음(이용 조건).
"""

from __future__ import annotations

import pytest

from tests.str.rag_baseline_support import (
    ab_overlap,
    chunk_ref,
    cosine_summary,
    lang_count,
    page_seq,
    parse_kinds,
    rank_of,
    recall_at,
)


def test_page_seq_counts_within_doc_page_in_load_order() -> None:
    order = [("d", 1, "a"), ("d", 1, "b"), ("d", 2, "c"), ("e", 1, "f"), ("d", 1, "a"), ("d", 1, "g")]
    assert page_seq(order) == {"a": 1, "b": 2, "c": 1, "f": 1, "g": 3}  # 다시 나온 a 는 셈에서 뺌


def test_chunk_ref_has_position_not_text() -> None:
    row = {"chunk_id": "a", "doc_id": "d", "page": 3, "lang": "en", "text": "secret body", "doc_title": "T"}
    assert chunk_ref(row, {"a": 2}) == {"chunk_id": "a", "doc_id": "d", "page": 3, "seq": 2, "lang": "en"}
    assert chunk_ref(row, {})["seq"] is None
    assert "secret" not in str(chunk_ref(row, {"a": 2}))


@pytest.mark.parametrize(
    ("arg", "want"), [("a", ("a",)), ("a,c", ("a", "c")), (" a , b , c ", ("a", "b", "c"))]
)
def test_parse_kinds_ok(arg: str, want: tuple[str, ...]) -> None:
    assert parse_kinds(arg) == want


@pytest.mark.parametrize("arg", ["", "b", "a,b", "c,a", "a,b,c,d", "a,a"])
def test_parse_kinds_rejects(arg: str) -> None:
    with pytest.raises(ValueError):
        parse_kinds(arg)


def test_recall_and_rank() -> None:
    top = ["x", "y", "z", "w"]
    assert recall_at(top, {"y", "q"}, 3) == 0.5 and recall_at(top, {"w"}, 3) == 0.0
    assert recall_at(top, set(), 3) == 0.0
    assert rank_of(top, "z") == 3 and rank_of(top, "nope") is None


def test_cosine_summary() -> None:
    assert cosine_summary([]) == {"n": 0, "min": None, "p25": None, "median": None, "p75": None, "max": None}
    assert cosine_summary([0.5]) == {"n": 1, "min": 0.5, "p25": 0.5, "median": 0.5, "p75": 0.5, "max": 0.5}
    s = cosine_summary([0.1, 0.2, 0.3, 0.4, 0.5])
    assert (s["n"], s["min"], s["median"], s["max"]) == (5, 0.1, 0.3, 0.5)
    assert (s["p25"], s["p75"]) == (0.2, 0.4)


def test_ab_overlap_split() -> None:
    assert ab_overlap(["x", "y", "z"], ["z", "y", "k"], {"y"}) == {"correct": ["y"], "wrong": ["z"]}


def test_lang_count() -> None:
    assert lang_count([{"lang": "ko"}, {"lang": "en"}, {"lang": "ko"}], "ko") == 2
