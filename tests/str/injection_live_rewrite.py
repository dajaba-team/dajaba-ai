"""SCRUM-147 live 하네스 — draft_service 흐름(DB 없이 조립):
생성 → attach_evidence → try_rewrite(Judge schema_retry=0 + NarrativeRewriter) → 최종 본문
→ run_code_checks + 평가자(judge_v3, 기본 재시도 1회) 후 점수 측정.

injection_live_generate.run_generate_rewrite_case(23) 가 이 모듈을 호출.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.shared.schemas.str import Facts, RevisedNarrativeSection
from aml_ai.str.application.draft_rewrite import NarrativeRewriter, try_rewrite
from aml_ai.str.domain import masking
from aml_ai.str.domain.fact_keys import attach_evidence, fact_keys
from aml_ai.str.domain.verification import run_code_checks
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.judge import Judge
from aml_ai.str.infrastructure.narrative_generator import NarrativeGenerator
from tests.str.injection_live_support import JudgeRun, invoke_judge, ok


class _RewriteCodeFailedCapture(logging.Handler):
    """draft_rewrite.rewrite_code_failed 로그에서 extra.checks 를 수집 (본문·값 없음, 세 필드만)."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.checks: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == "aml_ai.str.application.draft_rewrite" and record.msg == "rewrite_code_failed":
            self.checks.extend(getattr(record, "checks", []))


def _generate_phase(setup, settings, llm):  # type: ignore[no-untyped-def]
    facts = setup.facts
    facts_masked = masking.mask_for_llm(facts)
    keys = list(fact_keys(facts).keys())
    examples = FewshotStore(prompt_name=settings.narrative_prompt).pick_examples(facts.typology)
    deadline = time.monotonic() + settings.draft_budget_s
    generator = NarrativeGenerator(llm, settings, prompt_name=settings.narrative_prompt)
    t0 = time.monotonic()
    gen_before = generator.generate(
        facts_masked=facts_masked, fact_keys=keys, examples=examples,
        references=setup.references, notes=setup.notes, deadline=deadline,
    )  # fmt: skip
    return gen_before, int((time.monotonic() - t0) * 1000), facts_masked, keys, examples, deadline


def _run_single(setup, prompt_name: str) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """한 번 돌리기 — 생성·고쳐 쓰기·후 평가자 각각의 latency/tokens 를 반환 dict 에 모음."""
    settings = get_settings()
    llm = HttpLlmClient(settings)
    facts = setup.facts
    gen_before, gen_latency, facts_masked, keys, examples, deadline = _generate_phase(setup, settings, llm)
    narrative = attach_evidence(gen_before.narrative, facts)
    scope = list({*facts.inbound.transaction_ids, *facts.outbound.transaction_ids})
    cap = _RewriteCodeFailedCapture()
    rw_logger = logging.getLogger("aml_ai.str.application.draft_rewrite")
    rw_logger.addHandler(cap)
    try:
        rewrite_meta, final_narrative, final_gen = try_rewrite(
            settings=settings, facts=facts, facts_masked=facts_masked, fact_keys=keys,
            examples=examples, references=setup.references, notes=setup.notes,
            alert_rule_id=_rule_id(facts), evidence_scope=scope,
            original_narrative=narrative, original_gen=gen_before,
            judge=Judge(llm, settings, prompt_name="judge_v3", schema_retry=0, clock=time.monotonic),
            rewriter=NarrativeRewriter(llm, settings, clock=time.monotonic),
            clock=time.monotonic, deadline=deadline,
        )  # type: ignore[misc]  # fmt: skip
    finally:
        rw_logger.removeHandler(cap)
    rev = [RevisedNarrativeSection.model_validate(s.model_dump()) for s in final_narrative]
    code_checks = run_code_checks(facts, final_narrative, scope)
    post_judge: JudgeRun = invoke_judge(facts, rev, prompt_name)
    draft_total = (
        gen_latency
        + (rewrite_meta.critique_latency_ms or 0)
        + max(0, final_gen.latency_ms - gen_before.latency_ms)
    )
    return _assemble_result(
        prompt_name=prompt_name, rewrite_meta=rewrite_meta, final_gen=final_gen, gen_before=gen_before,
        gen_latency=gen_latency, post_judge=post_judge, code_checks=code_checks,
        narrative=final_narrative, draft_total_latency=draft_total,
        rewrite_code_failed_checks=cap.checks or None,
    )  # fmt: skip


def _rule_id(facts: Facts) -> str:
    from tools.record_rewrite import rule_id_from_facts

    return rule_id_from_facts(facts)


def _call_metrics(gen_before, final_gen, gen_latency, rewrite_meta, post_judge):  # type: ignore[no-untyped-def]
    return {
        "generate": {
            "tokens_in": gen_before.tokens_in,
            "tokens_out": gen_before.tokens_out,
            "latency_ms": gen_latency,
        },
        "critique": {
            "tokens_in": rewrite_meta.critique_tokens_in,
            "tokens_out": rewrite_meta.critique_tokens_out,
            "latency_ms": rewrite_meta.critique_latency_ms,
        },
        "rewrite": {
            "tokens_in": max(0, final_gen.tokens_in - gen_before.tokens_in),
            "tokens_out": max(0, final_gen.tokens_out - gen_before.tokens_out),
            "latency_ms": max(0, final_gen.latency_ms - gen_before.latency_ms),
        },
        "post_judge": {
            "tokens_in": post_judge.tokens_in,
            "tokens_out": post_judge.tokens_out,
            "latency_ms": post_judge.latency_ms,
        },
    }  # noqa: E501


def _assemble_result(**kw) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """결과 dict 조립 — 호출자 가독성용."""
    return {
        "judge_prompt": kw["prompt_name"],
        "rewrite_meta": kw["rewrite_meta"].model_dump(mode="json"),
        "post_scores": kw["post_judge"].scores,
        "post_status": kw["post_judge"].status,
        "post_code_checks": [
            {
                "check": c.check.value,
                "section": c.section.value if c.section else None,
                "match": c.match,
                "reason": c.reason.value if c.reason else None,
            }  # noqa: E501
            for c in kw["code_checks"]
        ],
        "call_metrics": _call_metrics(
            kw["gen_before"], kw["final_gen"], kw["gen_latency"], kw["rewrite_meta"], kw["post_judge"]
        ),
        "draft_total_latency_ms": kw["draft_total_latency"],
        "rewrite_code_failed_checks": kw.get("rewrite_code_failed_checks"),
        "narrative_text": {s.section.value: s.text for s in kw["narrative"]},
    }


def run_rewrite_case(case: int, n: int, prompt_name: str, setups, expects) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    setup = setups[case]()
    expect = expects[case]
    out: list[dict[str, Any]] = []
    for run in range(1, n + 1):
        result = _run_single(setup, prompt_name)
        result.update({
            "case": case, "run": run, "expect": expect,
            "ok": ok(result["post_scores"], expect),  # 후 평가 점수로 판단
        })  # fmt: skip
        out.append(result)
    return out
