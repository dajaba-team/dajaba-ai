"""SCRUM-268 — judge_v4 사전 기준 1·2 실행·기록 (손 실행 하네스 공용, docs/str/08 "judge_v4 사전 기준 측정").

254 `run_iteration` 그대로(코드 검사 실패 → CODE_FAILED · 평가자 예외 → VERIFY_UNAVAILABLE · 3표 raw) + 사례의
평가자(judge_v3/judge_v4)를 고르고 기준·역할·목표 항목을 기록에 더함. 주입 11 은 평가자 단독 호출. 회차마다 jsonl 한 줄.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.str.judge_stability_v4_run import run_iteration
from tests.str.judge_v4_criteria import CriteriaCase

# 프롬프트 이름 → (새 평가자, 그 평가자의 표 raw 를 모을 목록)
PromptJudgeFactory = Callable[[str], tuple[Any, list[Any]]]


def run_case(make_judge: PromptJudgeFactory, budget_s: float, case: CriteriaCase, run: int) -> dict[str, Any]:
    rec = run_iteration(lambda: make_judge(case.prompt), budget_s, case, run, judge_only=case.judge_only)  # type: ignore[arg-type]
    return rec | {
        "criterion": case.criterion,
        "prompt": case.prompt,
        "role": case.role,
        "target": case.target,
    }


def run_cases(
    cases: list[CriteriaCase], n: int, make_judge: PromptJudgeFactory, budget_s: float, out: Path
) -> None:
    """회차 하나 끝날 때마다 jsonl 한 줄 이어 쓰기."""
    out.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        for run in range(1, n + 1):
            rec = run_case(make_judge, budget_s, case, run)
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[268] {case.case_id} run={run} {rec['status']}")
