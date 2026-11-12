"""SCRUM-207 — Judge 중앙값 집계의 JudgeMeta 계산 (judge_vote 길이 가드로 분리).

입력: results(성공 ballot 리스트, run_no 포함) + errors(실패 exception, judge_meta 있을 수 있음).
규칙: 응답 받은 호출(성공 + 스키마 실패 exc.judge_meta) 전부 합산, attempts 는 submit 수 + 재시도 추가.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aml_ai.shared.schemas.str import JudgeMeta, LlmCheck, LlmCheckName

if TYPE_CHECKING:
    from aml_ai.str.infrastructure.judge import JudgeResult


def merge_checks_median(results: list[tuple[int, JudgeResult]]) -> list[LlmCheck]:
    """항목별 median 점수 + run 번호 작은 쪽 comment (docs/str/06)."""
    results.sort(key=lambda t: t[0])
    run_check_maps: list[tuple[int, dict[LlmCheckName, LlmCheck]]] = [
        (run_no, {c.check: c for c in r.checks}) for run_no, r in results
    ]
    merged: list[LlmCheck] = []
    for name in LlmCheckName:
        scored = [(rn, cm[name].score) for rn, cm in run_check_maps]
        scores_sorted = sorted(s for _, s in scored)
        n = len(scores_sorted)
        # 홀수 → 중간값 / 짝수 → 두 중간값 중 낮은 점수 (평가자는 엄격 쪽)
        median = scores_sorted[n // 2] if n % 2 else min(scores_sorted[n // 2 - 1], scores_sorted[n // 2])
        comment_run = next(rn for rn, s in scored if s == median)
        comment_check = next(cm[name] for rn, cm in run_check_maps if rn == comment_run)
        merged.append(LlmCheck(check=name, comment=comment_check.comment, score=median))
    return merged


def _sum_tokens_latency(
    results: list[tuple[int, JudgeResult]], errors: list[tuple[int, Exception]]
) -> tuple[int, int, list[int]]:
    """응답 받은 호출(성공 + 스키마 실패 exc.judge_meta) 의 tokens·latency 수집."""
    tokens_in = sum(r.meta.tokens_in for _, r in results)
    tokens_out = sum(r.meta.tokens_out for _, r in results)
    latencies = [r.meta.latency_ms for _, r in results]
    for _, exc in errors:
        jm = getattr(exc, "judge_meta", None)
        if jm is not None:
            tokens_in += jm.tokens_in
            tokens_out += jm.tokens_out
            latencies.append(jm.latency_ms)
    return tokens_in, tokens_out, latencies


def _sum_attempts(
    results: list[tuple[int, JudgeResult]],
    errors: list[tuple[int, Exception]],
    *,
    num_submitted: int,
) -> int:
    """submit 수 + 각 ballot 의 재시도 추가분 합 (SCRUM-144 규칙과 동형)."""
    attempts = num_submitted
    for _, r in results:
        if r.meta.attempts > 1:
            attempts += r.meta.attempts - 1
    for _, exc in errors:
        jm = getattr(exc, "judge_meta", None)
        if jm is not None and jm.attempts > 1:
            attempts += jm.attempts - 1
    return attempts


def _pick_llm_model(
    results: list[tuple[int, JudgeResult]],
    errors: list[tuple[int, Exception]],
    fallback: str,
) -> str:
    if results:
        return results[0][1].meta.llm_model
    for _, exc in errors:
        jm = getattr(exc, "judge_meta", None)
        if jm is not None:
            return jm.llm_model
    return fallback


def collect_meta(
    results: list[tuple[int, JudgeResult]],
    errors: list[tuple[int, Exception]],
    *,
    num_submitted: int,
    prompt_version: str,
    llm_model_fallback: str = "unknown",
) -> JudgeMeta | None:
    """응답 받은 호출 전부(스키마 실패 포함) tokens 합 · latency max · attempts 합.

    results·errors 둘 다 응답을 못 받은 경우 None — 호출이 아예 성립 못 함(즉시 연결 실패 등).
    """
    tokens_in, tokens_out, latencies = _sum_tokens_latency(results, errors)
    if not latencies and tokens_in == 0 and tokens_out == 0:
        return None
    return JudgeMeta(
        llm_model=_pick_llm_model(results, errors, llm_model_fallback),
        prompt_version=prompt_version,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=max(latencies) if latencies else 0,
        attempts=_sum_attempts(results, errors, num_submitted=num_submitted),
    )
