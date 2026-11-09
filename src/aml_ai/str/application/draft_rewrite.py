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
_SUPPORTED_PROMPT = "narrative_v2"  # SCRUM-147 — rewrite_v1 출력 스키마가 v2 7섹션

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
    ctx: _Ctx,
    reason: RewriteSkipReason,
    *,
    critique: dict[str, Any] | None = None,
    attempted: bool = False,
    gen: GenerationResult | None = None,
) -> _Result:
    meta = RewriteMeta(attempted=attempted, applied=False, skipped_reason=reason, **(critique or {}))
    return meta, ctx.original_narrative, gen if gen is not None else ctx.original_gen


def _critique_from_meta(meta) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {
        "critique_llm_model": meta.llm_model,
        "critique_tokens_in": meta.tokens_in,
        "critique_tokens_out": meta.tokens_out,
        "critique_latency_ms": meta.latency_ms,
    }  # noqa: E501


def _critique_fields(judge_result: JudgeResult) -> dict[str, Any]:
    out = _critique_from_meta(judge_result.meta)
    out["critique_scores"] = {c.check: c.score for c in judge_result.checks}
    return out


def _run_judge(ctx: _Ctx) -> tuple[JudgeResult | None, dict[str, Any]]:
    """평가자 호출. 실패면 (None, partial critique) — exc.judge_meta 있으면 모델·토큰·지연 보존."""
    try:
        return ctx.judge.run(
            ctx.facts_masked, ctx.original_narrative, deadline=ctx.deadline, fact_keys=ctx.fact_keys
        ), {}
    except Exception as exc:
        log.warning("rewrite_critique_error", extra={"reason": type(exc).__name__})
        jm = getattr(exc, "judge_meta", None)
        return None, _critique_from_meta(jm) if jm is not None else {"critique_llm_model": None}


def _merge_tokens(original: GenerationResult, rewrite_gen: GenerationResult | None) -> GenerationResult:
    """응답(usage) 받은 생성 모델 호출은 합산 — 본문은 호출자가 결정."""
    if rewrite_gen is None:
        return original
    return replace(
        original,
        tokens_in=original.tokens_in + rewrite_gen.tokens_in,
        tokens_out=original.tokens_out + rewrite_gen.tokens_out,
        latency_ms=original.latency_ms + rewrite_gen.latency_ms,
    )


def _fail_dict(c) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    return {"check": c.check.value, "section": c.section.value if c.section else None, "reason": c.reason.value if c.reason else None}  # fmt: skip  # noqa: E501


def _usage_from_exc(exc: Exception, prompt_version: str) -> GenerationResult | None:
    res = getattr(exc, "llm_result", None)
    if res is None:
        return None
    return GenerationResult(narrative=[], llm_model=res.model, prompt_version=prompt_version, tokens_in=res.tokens_in, tokens_out=res.tokens_out, latency_ms=res.latency_ms)  # fmt: skip  # noqa: E501


def _call_rewriter(
    ctx: _Ctx, judge_result: JudgeResult
) -> tuple[GenerationResult | None, RewriteSkipReason | None, GenerationResult | None]:
    """고쳐 쓰기 호출. (gen, fail_reason, usage_gen) — usage_gen 은 schema 실패 때 토큰만 있는 결과."""
    try:
        gen = ctx.rewriter.rewrite(
            facts_masked=ctx.facts_masked, fact_keys=ctx.fact_keys, examples=ctx.examples,
            references=ctx.references, notes=ctx.notes, original_narrative=ctx.original_narrative,
            critique=judge_result, deadline=ctx.deadline,
            paths_notice=build_paths_notice(alert_rule_id=ctx.alert_rule_id, facts=ctx.facts),
        )  # fmt: skip
    except LlmInvalidOutput as exc:
        return None, "schema", _usage_from_exc(exc, ctx.rewriter.prompt_version)
    except Exception as exc:
        log.warning("rewrite_call_error", extra={"reason": type(exc).__name__})
        return None, "rewrite_error", None
    return gen, None, None


def _phase_critique(ctx: _Ctx) -> _Result | tuple[JudgeResult, dict[str, Any]]:
    """①②③ 원본 코드 검사 → 평가자 앞 budget → 평가자 호출."""
    if not all(c.match for c in run_code_checks(ctx.facts, ctx.original_narrative, ctx.evidence_scope)):
        return _skip(ctx, "code_failed")
    if ctx.deadline - ctx.clock() < ctx.llm_timeout_s:
        return _skip(ctx, "budget")
    judge_result, critique_on_fail = _run_judge(ctx)
    if judge_result is None:
        return _skip(ctx, "critique_error", critique=critique_on_fail)
    return judge_result, _critique_fields(judge_result)


def _phase_rewrite(ctx: _Ctx, judge_result: JudgeResult, critique: dict[str, Any]) -> _Result:
    """④⑤⑥⑦⑧ — not_triggered / budget / 호출 / code_check / 성공."""
    scores = critique["critique_scores"]
    if all(s >= JUDGE_PASS_SCORE for s in scores.values()):
        return _skip(ctx, "not_triggered", critique=critique)
    if ctx.deadline - ctx.clock() < ctx.llm_timeout_s:
        return _skip(ctx, "budget", critique=critique)
    rewrite_gen, fail, usage_gen = _call_rewriter(ctx, judge_result)
    if rewrite_gen is None:
        assert fail is not None
        # SCRUM-147 — schema 실패여도 usage 있으면 토큰·지연 합산. rewrite_error(usage 없음)는 미합산.
        merged = _merge_tokens(ctx.original_gen, usage_gen)
        return _skip(ctx, fail, critique=critique, attempted=True, gen=merged)
    rewrite_narrative = attach_evidence(rewrite_gen.narrative, ctx.facts)
    merged = _merge_tokens(ctx.original_gen, rewrite_gen)
    rewrite_checks = run_code_checks(ctx.facts, rewrite_narrative, ctx.evidence_scope)
    fails = [_fail_dict(c) for c in rewrite_checks if not c.match]
    if fails:
        # SCRUM-147 — 응답 받은 호출은 본문 원본이어도 토큰·지연 합산 (★A 4 규칙 통일).
        # 로그 금지어 관문 통과: check·section·reason 세 필드만, draft_value·source_value 금지.
        log.warning("rewrite_code_failed", extra={"checks": fails})
        return _skip(ctx, "rewrite_code_failed", critique=critique, attempted=True, gen=merged)
    meta = RewriteMeta(attempted=True, applied=True, skipped_reason=None, **critique)
    return meta, rewrite_narrative, merged


def _run(ctx: _Ctx) -> _Result:
    pre = _phase_critique(ctx)
    if isinstance(pre[0], RewriteMeta):
        return pre  # type: ignore[return-value]
    judge_result, critique = pre  # type: ignore[assignment]
    return _phase_rewrite(ctx, judge_result, critique)


def try_rewrite(*, settings: Settings | None, **kw: Any) -> _Result | None:  # type: ignore[valid-type]
    """초안 생성 안 작성자–비평가 고쳐 쓰기 1회 (03 단계 8b). v2 초안에만 적용."""
    if kw["original_gen"].prompt_version != _SUPPORTED_PROMPT:
        return None  # SCRUM-147 — v1 초안은 고쳐 쓰기 안 함 (rewrite_v1 출력 스키마가 v2 7섹션)
    kw["llm_timeout_s"] = settings.llm_timeout_s if settings is not None else _DEFAULT_LLM_TIMEOUT_S
    return _run(_Ctx(**kw))
