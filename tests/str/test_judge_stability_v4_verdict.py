"""SCRUM-254 추가 검토 3차 — 사전 등록 표본을 다 채워야 기준 판정 (docs/str/08·09 "SCRUM-254 ★L-1 사전 기준"). LLM·DB 0.

기대 사건 목록(dry-run 과 같은 생성기)과 기록 대조 — 빠진 사건·회차 번호 중복·누락이면 미달.
`--n` ≠ 3 이나 v4 ≠ 18건이면 mode=exploratory, criterion_met = None(등록 기준으로 셀 수 없음).
"""

from __future__ import annotations

from typing import Any

from tests.str.judge_stability_v4 import build_cases
from tests.str.judge_stability_v4_tally import REGISTERED_N, REGISTERED_V4, run_conditions, verdict
from tests.str.v4_blind2_cases import case_facts, load_cases

B = case_facts(load_cases())
CASES = build_cases([("demo_7", B["sup_fan_in"]), ("demo_48", B["uns_fan_in"])])
EXPECTED = [(c.case_id, c.kind) for c in CASES]
OK = {"FIVE_W_ONE_H_COMPLETE": 5, "TYPOLOGY_CONSISTENT": 5, "NO_UNSUPPORTED_CLAIM": 5, "NO_SPECULATION": 5,
      "NO_INSTRUCTION_TEXT": 5}  # fmt: skip


def _rec(case_id: str, kind: str, run: int) -> dict[str, Any]:
    return {"case_id": case_id, "kind": kind, "run": run, "status": "PASSED", "scores": OK, "comments": {}}


def _c(n: int = 3, v4: int = 18) -> dict[str, Any]:
    return run_conditions(prompt="judge_v4", votes=3, pass_score=4, n=n, v4_cases=v4)


def _all_pass(n: int = 3) -> list[dict[str, Any]]:
    return [_rec(cid, kind, r) for cid, kind in EXPECTED for r in range(1, n + 1)]


def test_registered_sample_constants_match_case_builder() -> None:
    assert (REGISTERED_N, REGISTERED_V4) == (3, 18)
    assert sum(k == "v4" for _, k in EXPECTED) == 18 and len(EXPECTED) == 19
    v = verdict(_all_pass(), EXPECTED, _c())
    assert v == {"mode": "registered", "criterion_met": True, "reasons": []}


def test_missing_whole_case_fails() -> None:
    gone = EXPECTED[3][0]
    recs = [r for r in _all_pass() if r["case_id"] != gone]
    v = verdict(recs, EXPECTED, _c())
    assert v["mode"] == "registered" and v["criterion_met"] is False
    assert f"missing:{gone}" in v["reasons"]
    v2_gone = [r for r in _all_pass() if r["kind"] != "v2"]  # v2 대조가 통째로 빠져도 표본 불완전
    assert verdict(v2_gone, EXPECTED, _c())["criterion_met"] is False


def test_duplicate_iteration_number_fails() -> None:
    recs = _all_pass()
    target = EXPECTED[0][0]
    i = next(k for k, r in enumerate(recs) if r["case_id"] == target and r["run"] == 3)
    recs[i] = recs[i] | {"run": 2}  # 회차 1·2·2 — 3회째 없음 + 2회째 중복
    v = verdict(recs, EXPECTED, _c())
    assert v["criterion_met"] is False and f"runs:{target}" in v["reasons"]


def test_n1_run_is_exploratory_and_cannot_meet() -> None:
    v = verdict(_all_pass(n=1), EXPECTED, _c(n=1))
    assert v["mode"] == "exploratory" and v["criterion_met"] is None and v["reasons"] == ["n"]
    fewer = [e for e in EXPECTED if e[0] != "demo_48"]  # 시연 후보를 줄인 실행
    recs = [r for r in _all_pass() if r["case_id"] != "demo_48"]
    v = verdict(recs, fewer, _c(v4=17))
    assert v["mode"] == "exploratory" and v["criterion_met"] is None and v["reasons"] == ["v4_cases"]
