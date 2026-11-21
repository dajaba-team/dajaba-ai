"""SCRUM-308 ① 유사도 컷오프 판정 — 규칙 손 계산 · 반올림 경계(추가 검토 1) · 리포 결과 재계산 (docs/str/10 308 절 ①)."""

from __future__ import annotations

import json

import pytest

from tests.str import rag_eval_v3_cutoff as cut
from tests.str import rag_eval_v3_cutoff_guard as guard
from tests.str.rag_eval_v3_hybrid_support import forbidden_keys

EPS = cut.STORED_EPS


def cell(cid: str, cos: float) -> dict:
    return {"chunk_id": cid, "cosine": cos}


def query(qid: str, typ: str | None, uses: str, cells: list[dict]) -> dict:
    return {"id": qid, "typology": typ, "uses": [uses], "top10": cells}


def result(draft: list[dict], off: list[dict]) -> dict:
    return {
        "conditions": [
            {"name": guard.DRAFT_CONDITION, "filtered": True, "queries": draft},
            {
                "name": "on_ac_kw0",
                "filtered": True,
                "queries": [query("FX01", "FX_RELAY", "empty", [cell("z", 0.01)])],
            },
            {"name": "off_a_kw0", "filtered": False, "queries": off},
        ]
    }  # fmt: skip — 필터 켬 다른 조합(on_ac)은 판정 밖


CAND = {"candidates": {"FAN_IN": [
    {"chunk_id": "a1", "grade": 2, "db_tagged": True},
    {"chunk_id": "a2", "grade": 1, "db_tagged": True},
    {"chunk_id": "f1", "grade": 2, "db_tagged": False},  # 필터 켠 검색엔 못 나옴 — 초안 정답 아님
    {"chunk_id": "z0", "grade": 0, "db_tagged": True},
]}}  # fmt: skip


def test_adopts_when_no_answer_result_surely_removed() -> None:
    draft = [query("FI01", "FAN_IN", "hit", [cell("a1", 0.5), cell("w", 0.2), cell("a2", 0.4)]),
             query("FI02", "FAN_IN", "hit", [cell("a1", 0.6), cell("x", 0.9), cell("y", 0.1), cell("a2", 0.05)])]  # fmt: skip
    off = [
        query(
            "FX01", "FX_RELAY", "empty", [cell("n", 0.3), cell("m", 0.45), cell("k", 0.9), cell("deep", 0.0)]
        )
    ]
    out = cut.cutoff_verdict(result(draft, off), CAND)
    assert out["candidate_t"] == 0.4  # 4위(0.05)는 화면 밖 — 정답 칸 최소는 top-3 안에서만
    assert out["applied_t"] == pytest.approx(0.4 - EPS)
    assert (out["no_answer_cells"], out["no_answer_cells_removed"]) == (3, 1)  # 0.3 만, 4위는 안 셈
    assert (out["draft_wrong_cells"], out["draft_wrong_cells_removed"]) == (3, 2)
    assert out["answer_cells_lost"] == 0
    assert out["adopt"] is True and out["min_similarity"] == pytest.approx(0.4 - EPS)


def test_equal_value_is_boundary_and_kept() -> None:
    draft = [
        query("FI01", "FAN_IN", "hit", [cell("a1", 0.4), cell("f1", 0.39)])
    ]  # f1 은 db_tagged=false → 오답 칸
    off = [query("NR01", None, "reference", [cell("n", 0.4), cell("m", 0.7)])]
    out = cut.cutoff_verdict(result(draft, off), CAND)
    assert (
        out["no_answer_cells_removed"] == 0 and out["no_answer_boundary_cells"] == 0
    )  # 같은 값은 확실히 남음
    assert out["adopt"] is False and out["min_similarity"] == cut.KEEP


def test_rounded_up_answer_is_not_lost_and_boundary_holds() -> None:
    """추가 검토 1 — 실제 정답 0.3159506 은 0.315951 로 저장. 저장값 그대로 t 로 쓰면 검색에선 정답이 빠짐."""
    draft = [query("FI01", "FAN_IN", "hit", [cell("a1", 0.315951), cell("a2", 0.5)])]
    off = [query("FX01", "FX_RELAY", "empty", [cell("n", 0.315950)])]  # 실제 0.3159495~0.3159505 — 판별 못 함
    out = cut.cutoff_verdict(result(draft, off), CAND)
    assert out["applied_t"] == pytest.approx(0.3159505)
    assert out["applied_t"] <= 0.3159506  # 위로 반올림된 실제 정답도 남음
    assert out["no_answer_cells_removed"] == 0 and out["no_answer_boundary_cells"] == 1
    assert out["adopt"] is False  # 경계면 채택 보류


def test_no_answer_cells_from_draft_path_count() -> None:
    draft = [
        query("FI01", "FAN_IN", "hit", [cell("a1", 0.5)]),
        query("FX01", "FX_RELAY", "empty", [cell("n", 0.1)]),
    ]
    out = cut.cutoff_verdict(result(draft, []), CAND)
    assert out["no_answer_cells"] == 1 and out["adopt"] is True


def test_no_answer_cell_not_judged() -> None:
    out = cut.cutoff_verdict(result([query("FI01", "FAN_IN", "hit", [cell("w", 0.5)])], []), CAND)
    assert out == {"judged": False, "reason": "초안 경로 정답 칸 0", "min_similarity": cut.KEEP}


def test_repo_cutoff_result_matches_recomputation() -> None:
    if not cut.CUTOFF_FILE.exists():
        pytest.skip("result_308_cutoff.json 없음 — 다시 돌리기 전")
    doc = json.loads(cut.CUTOFF_FILE.read_text(encoding="utf-8"))
    loaded, digests, reason = guard.read_inputs(cut.REPO)
    assert reason is None and loaded is not None
    assert doc["verdict"] == cut.cutoff_verdict(loaded[guard.RESULT_307], loaded[guard.CANDIDATES])
    assert doc["criteria_commit"] == guard.CRITERIA_COMMIT
    assert doc["result_307_sha256"] == digests[guard.RESULT_307]
    assert forbidden_keys(doc) == []
