"""SCRUM-207 — Judge N 중앙값 집계 (verify 경로, docs/str/06 "N회 중앙값").

`run_votes` 가 병렬 호출 + 집계. `Judge.run` 이 `self._votes > 1` 일 때 이 함수를 쓴다.
`ThreadPoolExecutor` 는 `judge_vote` 모듈 속성이라 테스트에서 monkeypatch 로 spy 가능.

SCRUM-207 (Codex adversarial, 2026-11-12):
- 성공 <2 또는 `BudgetExceeded` 로 올라가는 예외에도 **응답 받은 호출의 judge_meta 를 붙여** 던진다
  (`verification_runs.judge_*` 저장이 null 로 끊기는 걸 막음, SCRUM-144·92 규칙과 동형).
- `ThreadPoolExecutor` 는 `contextvars.copy_context()` 를 제출마다 떠서 전달 — request_id 가 ballot
  스레드까지 넘어가 `llm_call`·`judge_invalid_output` 로그에 상위 request_id 가 남는다.

집계 산식(tokens·latency·attempts·comment·sections) 은 `judge_meta.py` 로 분리 — 파일 길이 가드.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from aml_ai.shared.errors import BudgetExceeded, LlmUnavailable
from aml_ai.str.infrastructure.judge_meta import collect_meta, merge_checks_median

if TYPE_CHECKING:
    from aml_ai.str.infrastructure.judge import JudgeResult

log = logging.getLogger(__name__)


def run_votes(
    *,
    votes: int,
    call_once: Callable[[], JudgeResult],
    clock: Callable[[], float],
    deadline: float | None,
    prompt_version: str,
) -> JudgeResult:
    """N 병렬 호출 → 항목별 중앙값 집계.

    executor 는 **직접** 만들고 finally 에서 `shutdown(wait=False, cancel_futures=True)` —
    `with` 블록은 돌고 있는 스레드를 기다려 deadline 을 넘긴다 (09 SCRUM-207 알고 남김).
    각 submit 은 `contextvars.copy_context()` 를 지녀 request_id 가 ballot 스레드까지 전파된다.
    """
    ex = ThreadPoolExecutor(max_workers=votes)
    try:
        futures: dict[Future, int] = {}
        for run_no in range(1, votes + 1):
            ctx = contextvars.copy_context()
            futures[ex.submit(ctx.run, call_once)] = run_no
        results, errors = _collect(futures, deadline=deadline, clock=clock, prompt_version=prompt_version)
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    if len(results) < 2:
        _raise_with_partial_meta(results, errors, votes=votes, prompt_version=prompt_version)
    return _aggregate(results, errors, num_submitted=len(futures), prompt_version=prompt_version)


def _raise_with_partial_meta(
    results: list[tuple[int, JudgeResult]],
    errors: list[tuple[int, Exception]],
    *,
    votes: int,
    prompt_version: str,
) -> None:
    """성공 < 2 — 응답 받은 호출의 judge_meta 를 붙여 raise (SCRUM-207 Codex finding 1)."""
    meta = collect_meta(results, errors, num_submitted=votes, prompt_version=prompt_version)
    exc: Exception = errors[0][1] if errors else LlmUnavailable("judge votes all timed out")
    if meta is not None:
        exc.judge_meta = meta  # type: ignore[attr-defined]
    raise exc


def _collect(
    futures: dict[Future, int],
    *,
    deadline: float | None,
    clock: Callable[[], float],
    prompt_version: str,
) -> tuple[list[tuple[int, JudgeResult]], list[tuple[int, Exception]]]:
    """as_completed 로 응답 수집. BudgetExceeded 도 수집한 meta 를 붙여 올린다."""
    results: list[tuple[int, JudgeResult]] = []
    errors: list[tuple[int, Exception]] = []
    remaining = max(0.0, deadline - clock()) if deadline is not None else None
    try:
        for fut in as_completed(futures, timeout=remaining):
            run_no = futures[fut]
            try:
                r = fut.result()
            except BudgetExceeded as budget_exc:
                for other in futures:
                    if not other.done():
                        other.cancel()
                meta = collect_meta(
                    results, errors, num_submitted=len(futures), prompt_version=prompt_version
                )
                if meta is not None:
                    budget_exc.judge_meta = meta  # type: ignore[attr-defined]
                raise
            except Exception as exc:
                log.warning("judge_vote_error", extra={"run": run_no, "reason": type(exc).__name__})
                errors.append((run_no, exc))
            else:
                results.append((run_no, r))
    except TimeoutError:
        # as_completed 가 deadline 넘김 — 미완료 future cancel 시도.
        # 돌고 있는 호출은 cancel 로 안 멈추므로 httpx 타임아웃에 맡김 (09 SCRUM-207).
        for fut in futures:
            if not fut.done():
                fut.cancel()
    return results, errors


def _aggregate(
    results: list[tuple[int, JudgeResult]],
    errors: list[tuple[int, Exception]],
    *,
    num_submitted: int,
    prompt_version: str,
) -> JudgeResult:
    """항목별 median·comment·sections·judge_meta 집계 (sections = run 1 호출)."""
    from aml_ai.str.infrastructure.judge import JudgeResult

    merged = merge_checks_median(results)
    first_run_result = results[0][1]
    meta = collect_meta(results, errors, num_submitted=num_submitted, prompt_version=prompt_version)
    assert meta is not None  # results 있으므로 보장
    return JudgeResult(checks=merged, meta=meta, sections=first_run_result.sections)
