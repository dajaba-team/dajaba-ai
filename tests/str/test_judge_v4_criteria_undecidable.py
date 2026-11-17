"""SCRUM-268 추가 검토 1차 — 근거가 없으면 통과가 아니라 판정 불가 (09 같은 날 "측정 전 기준 보충", 가짜 기록). LLM·DB 0.

기준 1 전 회차 평가자 실패 · judge_v3 0/4 · 기준 본문 전부 탈락 · 사례 하나만 점수 부족 → 판정 불가.
기준 2 코드 검사 통과 0건 · 기록 없음 → 판정 불가. 정상 기록 → 그대로 충족. 판정 불가는 criterion_met False + 이유.
"""

from __future__ import annotations

from typing import Any

from tests.str.judge_v4_criteria_tally import verdict
from tests.str.test_judge_v4_criteria_tally import CASES, _case, _cond, _good_records, _rec, _replace

EXPECTED = [c.case_id for c in CASES]


def _v(records: list[dict[str, Any]]) -> dict[str, Any]:
    return verdict(records, EXPECTED, _cond())


def test_normal_records_still_meet() -> None:
    v = _v(_good_records())
    assert v["criterion_met"] == {"c1": True, "c2": True}
    assert v["undecidable"] == {"c1": False, "c2": False} and v["reasons"] == []


def test_c1_all_judge_failures_is_undecidable() -> None:
    """전 회차 VERIFY_UNAVAILABLE — 예전엔 0 ≥ 0 으로 충족이었음."""
    recs = [_rec(_case(r["case_id"]), r["run"], "VERIFY_UNAVAILABLE") if r["criterion"] == 1 else r
            for r in _good_records()]  # fmt: skip
    v = _v(recs)
    assert v["criterion_met"]["c1"] is False and v["undecidable"]["c1"] is True
    assert (
        "c1:insufficient:judge_v3:base" in v["reasons"]
        and "c1:insufficient:judge_v4:inject_7" in v["reasons"]
    )
    assert v["criterion_met"]["c2"] is True  # 기준 2 는 따로


def test_c1_one_injection_short_of_scores_is_undecidable() -> None:
    """judge_v4 주입 8 만 점수 1회(나머지 평가자 실패) — 하나라도 판정 불가면 기준 1 판정 불가."""
    recs = _good_records()
    c = _case("c1:judge_v4:inject_8")
    for run in (1, 2):
        recs = _replace(recs, c.case_id, run, _rec(c, run, "VERIFY_UNAVAILABLE"))
    v = _v(recs)
    assert v["undecidable"]["c1"] is True and v["reasons"] == ["c1:insufficient:judge_v4:inject_8"]


def test_c1_judge_v3_zero_is_undecidable() -> None:
    """judge_v3 가 하나도 못 잡음(0/4) — 기준선이 없어 judge_v4 ≥ judge_v3 를 판정하지 않음."""
    recs = _good_records()
    for k in (7, 8, 10, 11):
        c = _case(f"c1:judge_v3:inject_{k}")
        recs = [_rec(c, r["run"]) if r["case_id"] == c.case_id else r for r in recs]  # 목표 항목 5
    v = _v(recs)
    assert v["c1"]["judge_v3"]["rate"] == 0.0 and v["c1"]["judge_v4"]["rate"] == 1.0
    assert v["criterion_met"]["c1"] is False and v["undecidable"]["c1"] is True
    assert "c1:no_baseline:judge_v3" in v["reasons"]


def test_c1_all_bases_excluded_is_undecidable() -> None:
    """두 기준 본문이 목표 항목 전부 3 — 사례가 전부 빠져 0 = 0. 빠진 사례는 이유에, 판정 불가."""
    low = {
        "NO_SPECULATION": 3,
        "NO_UNSUPPORTED_CLAIM": 3,
        "TYPOLOGY_CONSISTENT": 3,
        "FIVE_W_ONE_H_COMPLETE": 3,
    }
    recs = _good_records()
    for p in ("judge_v3", "judge_v4"):
        c = _case(f"c1:{p}:base")
        recs = [_rec(c, r["run"], **low) if r["case_id"] == c.case_id else r for r in recs]
    v = _v(recs)
    assert v["criterion_met"]["c1"] is False and v["undecidable"]["c1"] is True
    excluded = [r for r in v["reasons"] if r.startswith("c1:excluded:")]
    assert len(excluded) == 8 and "c1:no_baseline:judge_v3" in v["reasons"]


def test_c2_no_flip_passes_code_checks_is_undecidable() -> None:
    recs = [_rec(_case(r["case_id"]), r["run"], "CODE_FAILED") if r["role"] == "flip" else r
            for r in _good_records()]  # fmt: skip
    v = _v(recs)
    assert v["c2"]["evaluated"] == 0 and len(v["c2"]["code_failed"]) == 18
    assert v["criterion_met"]["c2"] is False and v["undecidable"]["c2"] is True
    assert v["criterion_met"]["c1"] is True


def test_c2_flip_with_judge_failure_is_not_caught_not_undecidable() -> None:
    """뒤집기 회차에 평가자 실패 — 그 뒤집기는 잡지 못함(기존대로), 판정 불가는 아님."""
    recs = _good_records()
    flip = next(c for c in CASES if c.criterion == 2)
    recs = _replace(recs, flip.case_id, 2, _rec(flip, 2, "VERIFY_UNAVAILABLE"))
    v = _v(recs)
    assert v["c2"]["not_caught"] == [flip.case_id]
    assert v["criterion_met"]["c2"] is False and v["undecidable"]["c2"] is False


def test_empty_expected_and_records_never_meets() -> None:
    """빈 기대 목록 + 빈 기록 — 어떤 기준도 충족 아님."""
    v = verdict([], [], _cond())
    assert v["criterion_met"] == {"c1": False, "c2": False}
    assert v["undecidable"] == {"c1": True, "c2": True}
