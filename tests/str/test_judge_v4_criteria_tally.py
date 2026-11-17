"""SCRUM-268 — judge_v4 사전 기준 1·2 판정·실행 기록 (09 SCRUM-268 사전 기준, 가짜 기록). LLM·DB 0.

기준 1: 기준 본문 목표 항목 n 중 2회 이상 ≥4 일 때만 판정 · 주입 목표 항목 n 중 2회 이상 ≤3 = 잡음 · 평가자 실패는
잡지 못함 · 비율 judge_v4 ≥ judge_v3 · 참고 12·23 판정 밖. 기준 2: 코드 검사 통과 뒤집기 전부 n 회 LLM_FAILED.
표본 완전성 · 실행 조건 다르면 exploratory · 실행: 사례 평가자 고르기·11 은 코드 검사 건너뜀·회차마다 기록.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aml_ai.shared.schemas.str import JudgeMeta, LlmCheck
from aml_ai.shared.schemas.str.verify import LlmCheckName
from tests.str.judge_stability_v4_run import read_records
from tests.str.judge_v4_criteria import build_criteria_cases
from tests.str.judge_v4_criteria_run import run_cases
from tests.str.judge_v4_criteria_tally import REGISTERED, run_conditions, verdict
from tests.str.v4_blind2_cases import case_facts, load_cases

BLIND2 = case_facts(load_cases())
DEMO = [("demo_7", BLIND2["sup_fan_in"]), ("demo_48", BLIND2["uns_fan_in"])]
CASES = build_criteria_cases(DEMO)
ALL5 = {c.value: 5 for c in LlmCheckName}


def _rec(case: Any, run: int, status: str = "PASSED", **low: int) -> dict[str, Any]:
    scores = {} if status in ("VERIFY_UNAVAILABLE", "CODE_FAILED") else ALL5 | low
    if status == "PASSED" and min(scores.values()) < 4:
        status = "LLM_FAILED"
    return {"case_id": case.case_id, "criterion": case.criterion, "prompt": case.prompt, "role": case.role,
            "target": case.target, "run": run, "status": status, "scores": scores}  # fmt: skip


def _good_records() -> list[dict[str, Any]]:
    """기준 본문·대조 전부 5 · 주입은 목표 항목 3 · 뒤집기는 NO_UNSUPPORTED 1 — 기준 1·2 모두 충족."""
    out = []
    for c in CASES:
        for run in (1, 2, 3):
            low = (
                {c.target: 3}
                if c.role == "inject"
                else {"NO_UNSUPPORTED_CLAIM": 1}
                if c.role == "flip"
                else {}
            )
            out.append(_rec(c, run, **low))
    return out


def _cond(**over: Any) -> dict[str, Any]:
    return run_conditions(**({"prompts": ["judge_v3", "judge_v4"], "votes": 3, "pass_score": 4, "n": 3,
                              "c1_injections": 4, "c2_flips": 18, "c2_controls": 18} | over))  # fmt: skip


def _replace(
    records: list[dict[str, Any]], case_id: str, run: int, rec: dict[str, Any]
) -> list[dict[str, Any]]:
    return [rec if (r["case_id"], r["run"]) == (case_id, run) else r for r in records]


def _case(case_id: str) -> Any:
    return next(c for c in CASES if c.case_id == case_id)


def test_registered_conditions() -> None:
    assert REGISTERED == {"prompts": ["judge_v3", "judge_v4"], "votes": 3, "pass_score": 4, "n": 3,
                          "c1_injections": 4, "c2_flips": 18, "c2_controls": 18}  # fmt: skip


def test_all_good_meets_both() -> None:
    v = verdict(_good_records(), [c.case_id for c in CASES], _cond())
    assert v["mode"] == "registered" and v["reasons"] == []
    assert v["criterion_met"] == {"c1": True, "c2": True}
    assert v["c1"]["judge_v3"]["rate"] == v["c1"]["judge_v4"]["rate"] == 1.0


def test_v4_misses_one_injection() -> None:
    recs = _good_records()
    c = _case("c1:judge_v4:inject_8")
    for run in (1, 2):
        recs = _replace(recs, c.case_id, run, _rec(c, run))  # 목표 항목 5 — 못 잡음
    v = verdict(recs, [x.case_id for x in CASES], _cond())
    assert v["c1"]["judge_v4"]["caught"] == [7, 10, 11] and v["c1"]["judge_v4"]["rate"] == 0.75
    assert v["criterion_met"]["c1"] is False


def test_base_gate_blocks_catch() -> None:
    """judge_v4 기준 본문이 TYPO 를 2회 이상 ≥4 로 못 받으면 주입 10 은 잡았어도 '잡지 못함'."""
    recs = _good_records()
    base = _case("c1:judge_v4:base")
    for run in (1, 2):
        recs = _replace(recs, base.case_id, run, _rec(base, run, TYPOLOGY_CONSISTENT=3))
    v = verdict(recs, [x.case_id for x in CASES], _cond())
    assert (
        10 not in v["c1"]["judge_v4"]["caught"]
        and v["c1"]["judge_v4"]["base_ok"]["TYPOLOGY_CONSISTENT"] is False
    )
    assert v["criterion_met"]["c1"] is False and v["undecidable"]["c1"] is False  # 미달(판정은 됨)
    assert "c1:excluded:judge_v4:inject_10:TYPOLOGY_CONSISTENT" in v["reasons"]  # 빠진 사례를 이유에


def test_unavailable_run_is_not_a_catch() -> None:
    recs = _good_records()
    c = _case("c1:judge_v3:inject_7")
    recs = _replace(recs, c.case_id, 1, _rec(c, 1, "VERIFY_UNAVAILABLE"))
    recs = _replace(recs, c.case_id, 2, _rec(c, 2))
    v = verdict(recs, [x.case_id for x in CASES], _cond())
    assert 7 not in v["c1"]["judge_v3"]["caught"]  # ≤3 은 1회뿐
    assert v["criterion_met"]["c1"] is True  # judge_v4 1.0 ≥ judge_v3 0.75


def test_references_do_not_count() -> None:
    recs = _good_records()
    for ref in ("c1:judge_v4:ref_12", "c1:judge_v4:ref_23", "c1:judge_v3:ref_23"):
        c = _case(ref)
        recs = [_rec(c, r["run"], TYPOLOGY_CONSISTENT=1) if r["case_id"] == ref else r for r in recs]
    assert verdict(recs, [x.case_id for x in CASES], _cond())["criterion_met"] == {"c1": True, "c2": True}


def test_flip_passed_once_fails_c2() -> None:
    recs = _good_records()
    flip = next(c for c in CASES if c.criterion == 2)
    recs = _replace(recs, flip.case_id, 3, _rec(flip, 3))  # PASSED — 뒤집기를 못 잡음
    v = verdict(recs, [x.case_id for x in CASES], _cond())
    assert v["criterion_met"]["c2"] is False and v["c2"]["not_caught"] == [flip.case_id]


def test_code_failed_flip_counted_apart() -> None:
    recs = _good_records()
    flip = next(c for c in CASES if c.criterion == 2)
    recs = [_rec(flip, r["run"], "CODE_FAILED") if r["case_id"] == flip.case_id else r for r in recs]
    v = verdict(recs, [x.case_id for x in CASES], _cond())
    assert v["c2"]["code_failed"] == [flip.case_id] and v["c2"]["evaluated"] == 17
    # 추가 검토 1차 — 코드 검사 통과 뒤집기가 18건 전부가 아니면 판정 불가(나머지 17건이 다 잡혀도)
    assert v["criterion_met"]["c2"] is False and v["undecidable"]["c2"] is True
    assert f"c2:code_failed:{flip.case_id}" in v["reasons"]


@pytest.mark.parametrize(("drop", "reason"), [(("c1:judge_v3:base", 3), "runs:c1:judge_v3:base"),
                                              (("c2:228:fan_in", 1), "runs:c2:228:fan_in")])  # fmt: skip
def test_incomplete_sample_fails(drop: tuple[str, int], reason: str) -> None:
    recs = [r for r in _good_records() if (r["case_id"], r["run"]) != drop]
    v = verdict(recs, [x.case_id for x in CASES], _cond())
    assert reason in v["reasons"] and v["criterion_met"] == {"c1": False, "c2": False}


@pytest.mark.parametrize(("over", "name"), [({"n": 1}, "n"), ({"prompts": ["judge_v3", "judge_v5"]}, "prompts"),
                                            ({"c2_flips": 16}, "c2_flips"), ({"c2_controls": 0}, "c2_controls"), ({"votes": 1}, "votes")])  # fmt: skip
def test_conditions_differ_exploratory(over: dict[str, Any], name: str) -> None:
    v = verdict(_good_records(), [x.case_id for x in CASES], _cond(**over))
    assert v["mode"] == "exploratory" and v["criterion_met"] is None and v["reasons"] == [name]


class _Judge:
    def __init__(self, prompt: str, seen: list[str]) -> None:
        self.prompt, self.seen = prompt, seen

    def run(self, *a: Any, **kw: Any) -> Any:
        self.seen.append(self.prompt)
        meta = JudgeMeta(llm_model="m", prompt_version=self.prompt, tokens_in=1, tokens_out=1, latency_ms=1,
                         attempts=3)  # fmt: skip
        return type("R", (), {"checks": [LlmCheck(check=c, comment="ok", score=5) for c in LlmCheckName],
                              "meta": meta})()  # fmt: skip


def test_runner_uses_case_prompt_and_skips_code_checks_for_11(tmp_path: Path) -> None:
    picked = [c for c in CASES if c.case_id in ("c1:judge_v3:inject_11", "c1:judge_v4:base", "c2:demo_7")]
    seen: list[str] = []
    out = tmp_path / "c.jsonl"
    run_cases(picked, 2, lambda prompt: (_Judge(prompt, seen), []), 30.0, out)
    recs = read_records(out)
    assert [(r["case_id"], r["run"]) for r in recs] == [(c.case_id, n) for c in picked for n in (1, 2)]
    assert seen == [c.prompt for c in picked for _ in (1, 2)]
    assert all(r["status"] == "PASSED" for r in recs)  # 11 도 CODE_FAILED 아님(단독 호출)
    assert {k for k in recs[0]} >= {"criterion", "prompt", "role", "target", "scores", "comments"}
