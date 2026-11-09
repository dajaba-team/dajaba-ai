"""SCRUM-147 — 초안 생성 안 작성자–비평가 고쳐 쓰기 1회 (docs/str/03 단계 8b, 05 rewrite_v1)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.schemas.str import Facts, Reference
from aml_ai.shared.schemas.str.draft import RewriteMeta, RewriteSkipReason
from aml_ai.shared.schemas.str.narrative import NarrativeSectionBase
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE
from aml_ai.str.domain.fact_keys import attach_evidence
from aml_ai.str.domain.models import Example, GenerationResult
from aml_ai.str.domain.verification import run_code_checks
from aml_ai.str.infrastructure.narrative_rewriter import (
    NarrativeRewriter,
    assemble_critique,
    build_paths_notice,
    render_rewrite_prompts,
    serialize_original_narrative,
)

if TYPE_CHECKING:
    from aml_ai.shared.config import Settings
    from aml_ai.str.infrastructure.judge import Judge, JudgeResult

__all__ = [
    "NarrativeRewriter",
    "assemble_critique",
    "build_paths_notice",
    "render_rewrite_prompts",
    "serialize_original_narrative",
    "try_rewrite",
]  # noqa: E501

log = logging.getLogger(__name__)
_DEFAULT_LLM_TIMEOUT_S = 35

_Result = tuple[RewriteMeta, list[NarrativeSectionBase], GenerationResult]


@dataclass
class _Ctx:
    """try_rewrite 단계들이 공유하는 입력 모음."""

    facts: Facts
    facts_masked: dict[str, Any]
    fact_keys: list[str]
    examples: list[Example]
    references: list[Reference]
    notes: str | None
    alert_rule_id: str
    evidence_scope: list[int]
    original_narrative: list[NarrativeSectionBase]
    original_gen: GenerationResult
    judge: Judge
    rewriter: NarrativeRewriter
    clock: Callable[[], float]
    deadline: float
    llm_timeout_s: int


def _skip(
    ctx: _Ctx, reason: RewriteSkipReason, *, critique: dict[str, Any] | None = None, attempted: bool = False
) -> _Result:
    meta = RewriteMeta(attempted=attempted, applied=False, skipped_reason=reason, **(critique or {}))
    return meta, ctx.original_narrative, ctx.original_gen


def _critique_fields(judge_result: JudgeResult) -> dict[str, Any]:
    m = judge_result.meta
    return {
        "critique_llm_model": m.llm_model,
        "critique_scores": {c.check: c.score for c in judge_result.checks},
        "critique_tokens_in": m.tokens_in,
        "critique_tokens_out": m.tokens_out,
        "critique_latency_ms": m.latency_ms,
    }


def _run_judge(ctx: _Ctx) -> JudgeResult | None:
    """평가자 호출. 예외면 None (critique_error 경로)."""
    try:
        return ctx.judge.run(
            ctx.facts_masked, ctx.original_narrative, deadline=ctx.deadline, fact_keys=ctx.fact_keys
        )
    except Exception as exc:
        log.warning("rewrite_critique_error", extra={"reason": type(exc).__name__})
        return None


def _call_rewriter(
    ctx: _Ctx, judge_result: JudgeResult
) -> tuple[GenerationResult | None, RewriteSkipReason | None]:
    try:
        gen = ctx.rewriter.rewrite(
            facts_masked=ctx.facts_masked,
            fact_keys=ctx.fact_keys,
            examples=ctx.examples,
            references=ctx.references,
            notes=ctx.notes,
            original_narrative=ctx.original_narrative,
            critique=judge_result,
            paths_notice=build_paths_notice(alert_rule_id=ctx.alert_rule_id, facts=ctx.facts),
            deadline=ctx.deadline,
        )
    except LlmInvalidOutput:
        return None, "schema"
    except Exception as exc:
        log.warning("rewrite_call_error", extra={"reason": type(exc).__name__})
        return None, "rewrite_error"
    return gen, None


def _phase_critique(ctx: _Ctx) -> _Result | tuple[JudgeResult, dict[str, Any]]:
    """①②③ 원본 코드 검사 → 평가자 앞 budget → 평가자 호출."""
    if not all(c.match for c in run_code_checks(ctx.facts, ctx.original_narrative, ctx.evidence_scope)):
        return _skip(ctx, "code_failed")
    if ctx.deadline - ctx.clock() < ctx.llm_timeout_s:
        return _skip(ctx, "budget")
    judge_result = _run_judge(ctx)
    if judge_result is None:
        return _skip(ctx, "critique_error", critique={"critique_llm_model": None})
    return judge_result, _critique_fields(judge_result)


def _phase_rewrite(ctx: _Ctx, judge_result: JudgeResult, critique: dict[str, Any]) -> _Result:
    """④⑤⑥⑦⑧ — not_triggered / budget / 호출 / code_check / 성공."""
    scores = critique["critique_scores"]
    if all(s >= JUDGE_PASS_SCORE for s in scores.values()):
        return _skip(ctx, "not_triggered", critique=critique)
    if ctx.deadline - ctx.clock() < ctx.llm_timeout_s:
        return _skip(ctx, "budget", critique=critique)
    rewrite_gen, fail = _call_rewriter(ctx, judge_result)
    if rewrite_gen is None:
        assert fail is not None
        return _skip(ctx, fail, critique=critique, attempted=True)
    rewrite_narrative = attach_evidence(rewrite_gen.narrative, ctx.facts)
    if not all(c.match for c in run_code_checks(ctx.facts, rewrite_narrative, ctx.evidence_scope)):
        return _skip(ctx, "rewrite_code_failed", critique=critique, attempted=True)
    merged = replace(
        ctx.original_gen,
        tokens_in=ctx.original_gen.tokens_in + rewrite_gen.tokens_in,
        tokens_out=ctx.original_gen.tokens_out + rewrite_gen.tokens_out,
        latency_ms=ctx.original_gen.latency_ms + rewrite_gen.latency_ms,
    )
    return (
        RewriteMeta(attempted=True, applied=True, skipped_reason=None, **critique),
        rewrite_narrative,
        merged,
    )


def _run(ctx: _Ctx) -> _Result:
    pre = _phase_critique(ctx)
    if isinstance(pre[0], RewriteMeta):
        return pre  # type: ignore[return-value]
    judge_result, critique = pre  # type: ignore[assignment]
    return _phase_rewrite(ctx, judge_result, critique)


def try_rewrite(*, settings: Settings | None, **kw: Any) -> _Result:  # type: ignore[valid-type]
    """초안 생성 안 작성자–비평가 고쳐 쓰기 1회 (03 단계 8b). kw 는 _Ctx 필드와 같음."""
    kw["llm_timeout_s"] = settings.llm_timeout_s if settings is not None else _DEFAULT_LLM_TIMEOUT_S
    return _run(_Ctx(**kw))
