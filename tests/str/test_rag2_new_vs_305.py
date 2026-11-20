"""SCRUM-306 ★B-4 새 3문서 행 합의 대 305 확인 등급·초벌 — 손 계산."""

from __future__ import annotations

from tools import rag2_new_vs_305 as nv


def test_compare_hand_example() -> None:
    agreed = {"a": frozenset({"CYCLE"}), "b": frozenset(), "c": frozenset({"GS", "CYCLE"})}
    confirmed = {"CYCLE": [{"chunk_id": "a", "grade": 0}], "GATHER_SCATTER": [{"chunk_id": "c", "grade": 2}]}
    draft = {
        t: [{"chunk_id": c, "grade": 0} for c in "abc"] for t in ("CYCLE", "SCATTER_GATHER", "GATHER_SCATTER")
    }
    res = nv.compare(agreed, confirmed, draft)
    assert res["CYCLE"]["확인"] == {"붙임/0": 1, "붙임/확인 안 함": 1, "안 붙임/확인 안 함": 1}
    assert res["CYCLE"]["초벌"] == {"붙임/0": 2, "안 붙임/0": 1}  # 초벌이 놓친 수 = 붙임/0
    assert res["GS"]["확인"] == {"붙임/≥1": 1, "안 붙임/확인 안 함": 2}
    assert res["SG"]["초벌"] == {"안 붙임/0": 3}


def test_compare_marks_missing_draft() -> None:
    res = nv.compare({"x": frozenset({"SG"})}, {}, {})
    assert res["SG"] == {"확인": {"붙임/확인 안 함": 1}, "초벌": {"붙임/초벌 없음": 1}}


def test_repo_305_files_load_and_new_untagged_have_no_confirmed_grade() -> None:
    from tools.rag2_agreement import expected_rows
    from tools.rag2_sample_new import NEW_DOCS

    confirmed, draft = nv.load_305()
    new = {r["chunk_id"] for r in expected_rows() if r["doc_id"] in NEW_DOCS}
    agreed = dict.fromkeys(new, frozenset({"CYCLE", "SG", "GS"}))
    res = nv.compare(agreed, confirmed, draft)
    for tag in nv.SHEET_TO_305:
        assert res[tag]["확인"] == {"붙임/확인 안 함": 10}  # 무태그 = 305 확인 범위 밖
        assert res[tag]["초벌"] == {"붙임/0": 10}  # 초벌은 259 모두 0
