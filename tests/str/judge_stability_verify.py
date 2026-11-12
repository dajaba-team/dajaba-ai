"""SCRUM-207 ★L-2 — 207 적용 뒤 verify 경로 N=3 병렬 집계 재측정 (손 실행).

judge_stability_live.py `--verify-votes` 모드에서 호출. Judge(votes=JUDGE_VOTES) 로 1 iteration =
3 병렬 호출 집계 결과(median scores·judge_meta tokens 합·latency max·attempts 합) 를 저장.

**세 호출 raw scores 도 보존** — `Judge._call_with_retry` 를 측정 도구에서 wrap 해 각 ballot 의
scores 를 수집한다 (SCRUM-126·131 재측정에서 쓸 자료).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.shared.schemas.str import Facts, RevisedNarrativeSection
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE, JUDGE_VOTES
from aml_ai.str.domain.fact_keys import fact_keys as domain_fact_keys
from aml_ai.str.infrastructure.judge import Judge, JudgeResult
from tests.str.judge_input_support import facts_for_case, original_narrative_for_case


def _prep_verify_inputs(case: int):  # type: ignore[no-untyped-def]
    """verify 경로 입력 왕복 재현 — facts 저장·load_draft 왕복 + narrative JSON 왕복."""
    facts_before = facts_for_case(case)
    facts = Facts.model_validate(facts_before.model_dump(mode="json"))
    narrative_generated = original_narrative_for_case(case)
    narrative = [
        RevisedNarrativeSection.model_validate(s.model_dump(mode="json")) for s in narrative_generated
    ]
    keys = list(domain_fact_keys(facts).keys())
    return facts, narrative, keys


def _wrap_call_with_retry(judge: Judge, ballots: list[JudgeResult], lock: threading.Lock) -> None:
    """측정 전용 — `_call_with_retry` 가 성공할 때마다 결과를 ballots 에 보존한다 (SCRUM-126·131 재측정 자료)."""
    original = judge._call_with_retry  # noqa: SLF001

    def wrapped(user: str, model: str, request_sections: list[str], deadline: float | None) -> JudgeResult:
        r = original(user, model, request_sections, deadline)
        with lock:
            ballots.append(r)
        return r

    judge._call_with_retry = wrapped  # type: ignore[method-assign]  # noqa: SLF001


def _ballots_payload(ballots: list[JudgeResult]) -> list[dict[str, Any]]:
    """iteration 마다 수집된 세 호출 raw — run_no 는 완료 순서이므로 보존용."""
    return [
        {
            "scores": {c.check.value: c.score for c in b.checks},
            "tokens_in": b.meta.tokens_in,
            "tokens_out": b.meta.tokens_out,
            "latency_ms": b.meta.latency_ms,
            "attempts": b.meta.attempts,
        }
        for b in ballots
    ]


def _one_iteration(
    http: HttpLlmClient,
    settings: Any,
    prompt_name: str,
    facts: Facts,
    narrative: list[RevisedNarrativeSection],
    keys: list[str],
    *,
    case: int,
    run: int,
) -> dict[str, Any]:
    judge = Judge(http, settings, prompt_name=prompt_name, votes=JUDGE_VOTES, schema_retry=1)
    ballots: list[JudgeResult] = []
    _wrap_call_with_retry(judge, ballots, threading.Lock())
    t0 = time.monotonic()
    result = judge.run(
        facts_masked=masking.mask_for_llm(facts),
        narrative=narrative,
        fact_keys=keys,
        deadline=time.monotonic() + settings.verify_budget_s,
    )
    elapsed = int((time.monotonic() - t0) * 1000)
    scores = {c.check.value: c.score for c in result.checks}
    status = "PASSED" if min(scores.values()) >= JUDGE_PASS_SCORE else "LLM_FAILED"
    rec: dict[str, Any] = {
        "case": case, "path": "verify", "run": run, "prompt": prompt_name,
        "scores": scores, "ballots": _ballots_payload(ballots),
        "status": status,
        "tokens_in": result.meta.tokens_in, "tokens_out": result.meta.tokens_out,
        "latency_ms_judge_meta": result.meta.latency_ms, "wall_clock_ms": elapsed,
        "attempts": result.meta.attempts, "votes": JUDGE_VOTES,
    }  # fmt: skip
    print(
        f"[verify-votes] case={case} run={run} status={status} "
        f"attempts={rec['attempts']} tokens_in={rec['tokens_in']} "
        f"wall_clock_ms={elapsed} judge_latency_ms={rec['latency_ms_judge_meta']} "
        f"ballots={len(ballots)}"
    )
    return rec


def run_verify_votes(cases: list[int], n: int, prompt_name: str) -> list[dict[str, Any]]:
    settings = get_settings()
    http = HttpLlmClient(settings)
    results: list[dict[str, Any]] = []
    for case in cases:
        facts, narrative, keys = _prep_verify_inputs(case)
        for run in range(1, n + 1):
            results.append(
                _one_iteration(http, settings, prompt_name, facts, narrative, keys, case=case, run=run)
            )
    return results
