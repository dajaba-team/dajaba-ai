"""SCRUM-268 추가 검토 2차 — 기준 2 잡음 = 목표 항목 + 원래 초안 대조 (09 같은 날 "측정 전 기준 보충", 가짜 기록). LLM·DB 0.

뒤집기 `NO_UNSUPPORTED_CLAIM` n 회 모두 ≤ 2 = 잡음(다른 항목 실패는 근거 아님) · 대조(원래 초안)가 n 중 2회 이상 ≥ 3
일 때만 판정, 낮으면 `c2:control_low`, 점수 부족이면 `c2:control_insufficient` — 판정 불가 · 충족 = 18건 전부 판정 + 전부 잡음.
"""

from __future__ import annotations

from typing import Any

from tests.str.judge_v4_criteria_tally import verdict
from tests.str.test_judge_v4_criteria_tally import CASES, _case, _cond, _good_records, _rec, _replace

EXPECTED = [c.case_id for c in CASES]
FLIPS = [c for c in CASES if c.role == "flip"]
NU = "NO_UNSUPPORTED_CLAIM"


def _v(records: list[dict[str, Any]]) -> dict[str, Any]:
    return verdict(records, EXPECTED, _cond())


def _set(records: list[dict[str, Any]], case_id: str, *per_run: dict[str, Any]) -> list[dict[str, Any]]:
    """case_id 의 회차 1..n 을 per_run 순서대로 — {"status": ..} 또는 점수 낮춤 {항목: 점수}."""
    c = _case(case_id)
    for run, spec in enumerate(per_run, start=1):
        spec = dict(spec)
        status = spec.pop("status", "PASSED")
        records = _replace(records, case_id, run, _rec(c, run, status, **spec))
    return records


def test_normal_records_meet_c2() -> None:
    v = _v(_good_records())
    assert v["criterion_met"]["c2"] is True and v["undecidable"]["c2"] is False
    assert len(v["c2"]["caught"]) == 18 and v["c2"]["not_caught"] == []


def test_review_repro_unrelated_failures_are_not_catches() -> None:
    """추가 검토 2차 재현: 뒤집기 54회 전부 FIVE_W=1·NO_UNSUPPORTED=5·TYPO=5 — LLM_FAILED 지만 잡음 아님 → 미달."""
    recs = [_rec(_case(r["case_id"]), r["run"], FIVE_W_ONE_H_COMPLETE=1) if r["role"] == "flip" else r
            for r in _good_records()]  # fmt: skip
    assert all(r["status"] == "LLM_FAILED" for r in recs if r["role"] == "flip")
    v = _v(recs)
    assert v["criterion_met"]["c2"] is False and v["undecidable"]["c2"] is False
    assert len(v["c2"]["not_caught"]) == 18 and v["c2"]["caught"] == []


def test_control_low_is_undecidable() -> None:
    flip = FLIPS[0]
    sid = flip.case_id.removeprefix("c2:")
    recs = _set(_good_records(), f"c2ctl:{sid}", {NU: 2}, {NU: 2}, {})  # 원래 초안이 이미 NU 2·2·5
    v = _v(recs)
    assert v["criterion_met"]["c2"] is False and v["undecidable"]["c2"] is True
    assert v["reasons"] == [f"c2:control_low:{sid}"]


def test_control_insufficient_is_undecidable() -> None:
    sid = FLIPS[1].case_id.removeprefix("c2:")
    recs = _set(
        _good_records(),
        f"c2ctl:{sid}",
        {"status": "VERIFY_UNAVAILABLE"},
        {"status": "VERIFY_UNAVAILABLE"},
        {},
    )
    v = _v(recs)
    assert v["undecidable"]["c2"] is True and v["reasons"] == [f"c2:control_insufficient:{sid}"]


def test_control_other_item_failures_do_not_matter() -> None:
    """대조가 FIVE_W 1(254 1차 ③ 같은 기존 결함)이어도 NU ≥ 3 이면 판정에 넣음."""
    sid = FLIPS[2].case_id.removeprefix("c2:")
    low = {"FIVE_W_ONE_H_COMPLETE": 1, "TYPOLOGY_CONSISTENT": 3}
    v = _v(_set(_good_records(), f"c2ctl:{sid}", low, low, low))
    assert v["criterion_met"]["c2"] is True


def test_flip_at_existing_problem_level_is_not_caught() -> None:
    """뒤집기 NU 3·3·3 — 기존 문제("FACTS 에 없는 정황") 칸, 블록과 반대(1점) 칸이 아님 → 잡지 못함."""
    flip = FLIPS[3]
    v = _v(_set(_good_records(), flip.case_id, {NU: 3}, {NU: 3}, {NU: 3}))
    assert v["c2"]["not_caught"] == [flip.case_id] and v["criterion_met"]["c2"] is False
    assert v["undecidable"]["c2"] is False


def test_flip_one_run_above_two_is_not_caught() -> None:
    """n 회 모두 ≤ 2 — 1·1·3 이면 잡지 못함, 1·2·2 면 잡음."""
    a, b = FLIPS[4], FLIPS[5]
    recs = _set(_good_records(), a.case_id, {NU: 1}, {NU: 1}, {NU: 3})
    recs = _set(recs, b.case_id, {NU: 1}, {NU: 2}, {NU: 2})
    v = _v(recs)
    assert v["c2"]["not_caught"] == [a.case_id] and b.case_id in v["c2"]["caught"]


def test_flip_caught_with_control_at_three() -> None:
    """뒤집기 1·1·1 + 대조 NU 3·3·3 — 대조가 경계(≥3)라 판정에 들어가고 잡음."""
    flip = FLIPS[6]
    sid = flip.case_id.removeprefix("c2:")
    recs = _set(_good_records(), flip.case_id, {NU: 1}, {NU: 1}, {NU: 1})
    recs = _set(recs, f"c2ctl:{sid}", {NU: 3}, {NU: 3}, {NU: 3})
    v = _v(recs)
    assert flip.case_id in v["c2"]["caught"] and v["criterion_met"]["c2"] is True


def test_flip_judge_failure_is_not_caught() -> None:
    """1차 그대로 — 뒤집기 회차에 평가자 실패가 있으면 잡지 못함(판정 불가 아님)."""
    flip = FLIPS[7]
    v = _v(_set(_good_records(), flip.case_id, {NU: 1}, {"status": "VERIFY_UNAVAILABLE"}, {NU: 1}))
    assert v["c2"]["not_caught"] == [flip.case_id] and v["undecidable"]["c2"] is False
