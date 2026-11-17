"""SCRUM-254 ★L-1 — 회차 기록·평가자 실패 (추가 검토 1차, docs/str/08 "평가자 흔들림 — v4 초안"). LLM·DB 0.

평가자 예외는 VERIFY_UNAVAILABLE(남은 judge_meta·예외 종류만) · 회차마다 jsonl 에 바로 이어 써서 앞 기록이 남음 ·
VERIFY_UNAVAILABLE 은 PASSED 아님 → 사전 기준 미달 · 표에 따로 칸.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.schemas.str import JudgeMeta, LlmCheck
from aml_ai.shared.schemas.str.verify import LlmCheckName
from tests.str.judge_stability_v4 import build_cases
from tests.str.judge_stability_v4_run import read_records, run_cases
from tests.str.judge_stability_v4_tally import meets_criterion, render_table, tally
from tests.str.v4_blind2_cases import case_facts, load_cases

META = JudgeMeta(
    llm_model="m", prompt_version="judge_v3", tokens_in=100, tokens_out=10, latency_ms=5, attempts=3
)


class _Result:
    def __init__(self) -> None:
        self.checks = [LlmCheck(check=c, comment="근거 있음", score=5) for c in LlmCheckName]
        self.meta = META


class _FakeJudge:
    """회차 번호(공유 카운터)가 fail_on 이면 예외 — 남은 judge_meta 를 붙여 던짐(judge_vote 와 같게)."""

    calls = 0

    def __init__(self, fail_on: int) -> None:
        self.fail_on = fail_on

    def run(self, *a: Any, **kw: Any) -> _Result:
        _FakeJudge.calls += 1
        if _FakeJudge.calls == self.fail_on:
            exc = LlmUnavailable("표 부족 — 본문은 기록 안 함")
            exc.judge_meta = META.model_copy(update={"tokens_in": 40, "attempts": 1})  # type: ignore[attr-defined]
            raise exc
        return _Result()


def test_third_run_failure_keeps_earlier_records(tmp_path: Path) -> None:
    case = build_cases([])[0]  # 228:fan_in — 코드 검사 0
    _FakeJudge.calls = 0
    out = tmp_path / "runs.jsonl"
    try:
        run_cases([case], 3, lambda: (_FakeJudge(fail_on=3), []), 30.0, out)
    finally:
        _FakeJudge.calls = 0
    recs = read_records(out)
    assert [r["status"] for r in recs] == ["PASSED", "PASSED", "VERIFY_UNAVAILABLE"]
    last = recs[-1]
    assert last["error_type"] == LlmUnavailable("x").code and last["judge_meta"]["tokens_in"] == 40
    assert "본문" not in str(last)  # 예외 메시지는 안 남김
    s = tally(recs)
    assert (s[case.case_id]["passed"], s[case.case_id]["unavailable"]) == (2, 1)
    assert meets_criterion(s, n=3) is False
    assert "| 1 |" in render_table(s)  # 평가자 실패 칸


def test_lines_written_per_iteration(tmp_path: Path) -> None:
    """한 회차가 끝날 때마다 한 줄 — 두 사건 × 2회 = 4줄, 순서대로."""
    cases = build_cases([("demo_x", case_facts(load_cases())["sup_fan_in"])])[:2]
    _FakeJudge.calls = 0
    out = tmp_path / "runs.jsonl"
    run_cases(cases, 2, lambda: (_FakeJudge(fail_on=-1), []), 30.0, out)
    _FakeJudge.calls = 0
    recs = read_records(out)
    assert [(r["case_id"], r["run"]) for r in recs] == [(c.case_id, n) for c in cases for n in (1, 2)]
    assert meets_criterion(tally(recs), n=2) is True
