"""SCRUM-254 ★L-1 — 사건 × 회차 실행·기록 (손 실행 하네스 공용, docs/str/08 "평가자 흔들림 — v4 초안").

실제 verify 와 같게: 코드 검사 실패면 CODE_FAILED(평가자 안 감) · 평가자 예외(타임아웃·전송 오류·표 부족)는
VerifyService 와 같은 규칙으로 VERIFY_UNAVAILABLE(남은 judge_meta·예외 종류 이름만 — 메시지 본문 안 남김).
회차마다 `_tmp` jsonl 에 한 줄씩 바로 이어 씀 — 중간에 멈춰도 앞 회차 기록이 남음. 표·판정은 그 파일을 다시 읽어 만듦.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aml_ai.shared.errors import AiError
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE
from tests.str.judge_stability_v4 import V4Case, code_check_failures, verify_inputs

# 회차마다 새 평가자 + 그 평가자의 표(ballot) raw 를 모을 목록
JudgeFactory = Callable[[], tuple[Any, list[Any]]]


def _ballots(ballots: list[Any]) -> list[dict[str, Any]]:
    return [{"scores": {c.check.value: c.score for c in b.checks}, "comments": {c.check.value: c.comment for c in b.checks},
             "tokens_in": b.meta.tokens_in, "tokens_out": b.meta.tokens_out} for b in ballots]  # fmt: skip


def run_iteration(
    make_judge: JudgeFactory, budget_s: float, case: V4Case, run: int, *, judge_only: bool = False
) -> dict[str, Any]:
    """judge_only — 코드 검사 건너뛰고 평가자 단독 호출(SCRUM-268 기준 1 주입 11, 127 측정과 같은 규칙)."""
    rec: dict[str, Any] = {"case_id": case.case_id, "kind": case.kind, "run": run}
    failures = 0 if judge_only else code_check_failures(case)
    if failures:  # 실제 verify 처럼 평가자까지 안 감
        return rec | {"status": "CODE_FAILED", "scores": {}, "comments": {}, "code_check_failures": failures}
    judge, ballots = make_judge()
    facts_masked, narrative, keys = verify_inputs(case)
    t0 = time.monotonic()
    try:
        result = judge.run(facts_masked, narrative, fact_keys=keys, deadline=time.monotonic() + budget_s)
    except Exception as exc:  # verify_service._decide 와 같은 규칙 — VERIFY_UNAVAILABLE
        meta = getattr(exc, "judge_meta", None)
        return rec | {"status": "VERIFY_UNAVAILABLE", "scores": {}, "comments": {},
                      "error_type": exc.code if isinstance(exc, AiError) else type(exc).__name__,
                      "judge_meta": meta.model_dump(mode="json") if meta is not None else None,
                      "ballots": _ballots(ballots), "wall_clock_ms": int((time.monotonic() - t0) * 1000)}  # fmt: skip
    scores = {c.check.value: c.score for c in result.checks}
    return rec | {"status": "PASSED" if min(scores.values()) >= JUDGE_PASS_SCORE else "LLM_FAILED", "scores": scores,
                  "comments": {c.check.value: c.comment for c in result.checks}, "ballots": _ballots(ballots),
                  "tokens_in": result.meta.tokens_in, "tokens_out": result.meta.tokens_out,
                  "wall_clock_ms": int((time.monotonic() - t0) * 1000), "attempts": result.meta.attempts}  # fmt: skip


def run_cases(cases: list[V4Case], n: int, make_judge: JudgeFactory, budget_s: float, out: Path) -> None:
    """회차 하나 끝날 때마다 jsonl 한 줄 이어 쓰기."""
    out.parent.mkdir(parents=True, exist_ok=True)
    for case in cases:
        for run in range(1, n + 1):
            rec = run_iteration(make_judge, budget_s, case, run)
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"[v4] {case.case_id} run={run} {rec['status']}")


def read_records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
