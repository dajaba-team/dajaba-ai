"""SCRUM-275 판정 (docs/str/10 "판정 기준", 09 2026-11-19 — 정답 보기 전 고정). 순수.

① 보류용 채운 칸 중 정답(grade ≥ 1) 비율 ≥ 0.75 ② 정답 없는 질의 8개 전부 0건(개발+보류)
③ 30개 모두 지금 경로 상위 결과 순서·chunk_id 그대로(개발+보류) ④ 보류용 채운 칸 6 미만 → 판정 안 함.
"""

from __future__ import annotations

from tests.str.rag_eval_v2_support import (
    VERDICT_MIN_SLOTS,
    VERDICT_RATIO_MIN,
    QueryRun,
    verdict,
)


def _cycle(qid: str, split: str, grades: list[int]) -> QueryRun:
    return QueryRun(qid, split, "CYCLE", False, ["t1", "t2"], ["t1", "t2", "u"], grades)


def _empty(qid: str, split: str, on: list[str] | None = None) -> QueryRun:
    return QueryRun(qid, split, "SCATTER_GATHER", True, [], on or [], [])


def _runs(holdout_grades: list[int], *, extra: list[QueryRun] | None = None) -> list[QueryRun]:
    runs = [_cycle(f"H{i}", "holdout", [g]) for i, g in enumerate(holdout_grades)]
    runs += [_cycle("D1", "dev", [0]), _empty("D2", "dev"), _empty("H9", "holdout")]
    return runs + (extra or [])


def test_registered_numbers() -> None:
    assert VERDICT_RATIO_MIN == 0.75 and VERDICT_MIN_SLOTS == 6


def test_passes_at_exactly_six_of_eight() -> None:
    out = verdict(_runs([1, 2, 1, 1, 1, 1, 0, 0]))
    assert out["ratio"] == 0.75 and out["filled_slots"] == 8 and out["met"] is True and out["judged"] is True


def test_fails_below_ratio() -> None:
    out = verdict(_runs([1, 1, 1, 1, 1, 0, 0, 0]))
    assert out["met"] is False and out["judged"] is True


def test_dev_grades_do_not_count_for_ratio() -> None:
    out = verdict(_runs([1] * 6, extra=[_cycle("D3", "dev", [0])] * 5))
    assert out["ratio"] == 1.0


def test_too_few_slots_is_not_judged() -> None:
    out = verdict(_runs([1, 1, 1, 1, 1]))
    assert out["filled_slots"] == 5 and out["judged"] is False and out["met"] is False


def test_empty_query_with_result_in_dev_fails() -> None:
    out = verdict(_runs([1] * 8, extra=[_empty("D4", "dev", on=["x"])]))
    assert out["empty_ok"] is False and out["met"] is False


def test_changed_first_pass_in_dev_fails() -> None:
    changed = QueryRun("D5", "dev", "FAN_IN", False, ["a", "b", "c"], ["a", "c", "b"], [])
    out = verdict(_runs([1] * 8, extra=[changed]))
    assert out["first_ok"] is False and out["met"] is False


def test_partial_first_pass_reordered_fails() -> None:
    swapped = QueryRun("D6", "dev", "CYCLE", False, ["t1", "t2"], ["t2", "t1", "u"], [1])
    assert verdict(_runs([1] * 8, extra=[swapped]))["first_ok"] is False


def test_slot_count_mismatch_is_rejected() -> None:
    import pytest

    bad = QueryRun("H7", "holdout", "CYCLE", False, ["t1", "t2"], ["t1", "t2", "u"], [1, 1])
    with pytest.raises(ValueError, match="grades"):
        verdict(_runs([1] * 8, extra=[bad]))


def test_grade_zero_slot_counts_as_wrong() -> None:
    run = QueryRun("H8", "holdout", "CYCLE", False, ["t1", "t2"], ["t1", "t2", "u"], [0])
    out = verdict(_runs([1] * 6, extra=[run, run]))
    assert out["filled_slots"] == 8 and out["correct_slots"] == 6
