"""SCRUM-254 추가 검토 4차 — 실행 조건도 사전 등록과 같아야 등록 판정 (docs/str/09 "SCRUM-254 ★L-1 사전 기준"). LLM·DB 0.

judge 프롬프트 judge_v3 · 표 수 3 · 통과 기준 4 · n 3 · v4 18건 — 하나라도 다르면 mode=exploratory,
criterion_met=None, 이유 = 다른 조건 이름. 시작 mode 와 최종 판정이 같은 함수(mode_of)를 씀.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.str.judge_stability_v4_tally import REGISTERED, mode_of, run_conditions, verdict
from tests.str.test_judge_stability_v4_verdict import EXPECTED, _all_pass


def _cond(**changes: Any) -> dict[str, Any]:
    base = run_conditions(prompt="judge_v3", votes=3, pass_score=4, n=3, v4_cases=18)
    return base | changes


def test_registered_values_from_09() -> None:
    assert REGISTERED == {"prompt": "judge_v3", "votes": 3, "pass_score": 4, "n": 3, "v4_cases": 18}


def test_all_registered_is_registered() -> None:
    assert mode_of(_cond()) == ("registered", [])
    assert verdict(_all_pass(), EXPECTED, _cond()) == {
        "mode": "registered",
        "criterion_met": True,
        "reasons": [],
    }


@pytest.mark.parametrize(
    ("changes", "reason"),
    [({"prompt": "judge_v2"}, "prompt"), ({"votes": 1}, "votes"), ({"pass_score": 3}, "pass_score")],
)
def test_condition_differs_is_exploratory(changes: dict[str, Any], reason: str) -> None:
    c = _cond(**changes)
    assert mode_of(c) == ("exploratory", [reason])
    v = verdict(_all_pass(), EXPECTED, c)  # 표본은 다 채워도
    assert v == {"mode": "exploratory", "criterion_met": None, "reasons": [reason]}
