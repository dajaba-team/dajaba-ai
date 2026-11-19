"""SCRUM-275 정답 파일 — 초벌 펼치기 · 확인 여부 · 등급 조회 (docs/str/10 "평가 세트"). 순수."""

from __future__ import annotations

from tests.str.rag_eval_v2_support import expand_answers, grade_lookup, unchecked

_DRAFT = {
    "prompt_version": "rag_answer_v1",
    "by_typology": {"CYCLE": [{"chunk_id": "c1", "doc_id": "d", "page": 3, "pos": 2, "grade": 1}]},
}
_QUERIES = [
    {"id": "H01", "typology": "CYCLE", "expect_empty": False},
    {"id": "H02", "typology": "FAN_IN", "expect_empty": False},
    {"id": "H03", "typology": "SCATTER_GATHER", "expect_empty": True},
]


def test_expand_per_query_without_text_and_unchecked() -> None:
    out = expand_answers(_DRAFT, _QUERIES)
    assert [e["query_id"] for e in out["queries"]] == ["H01", "H02"]  # 정답 없는 질의 빠짐
    first = out["queries"][0]
    assert first["answers"] == [{"chunk_id": "c1", "doc_id": "d", "page": 3, "pos": 2, "grade": 1}]
    assert first["draft"] == "llm:rag_answer_v1" and first["checked_by"] is None
    assert out["queries"][1]["answers"] == []
    assert "text" not in str(out["queries"])


def test_expand_copies_lists() -> None:
    out = expand_answers(_DRAFT, _QUERIES)
    out["queries"][0]["answers"][0]["grade"] = 0
    assert _DRAFT["by_typology"]["CYCLE"][0]["grade"] == 1


def test_unchecked_needs_both_fields() -> None:
    doc = {"queries": [
        {"query_id": "a", "checked_by": "x", "checked_at": "2026-11-20", "answers": []},
        {"query_id": "b", "checked_by": "x", "checked_at": None, "answers": []},
        {"query_id": "c", "checked_by": None, "checked_at": None, "answers": []},
    ]}  # fmt: skip
    assert unchecked(doc) == ["b", "c"]


def test_grade_lookup() -> None:
    assert grade_lookup(expand_answers(_DRAFT, _QUERIES)) == {"H01": {"c1": 1}, "H02": {}}
