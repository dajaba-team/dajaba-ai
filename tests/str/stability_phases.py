"""안정화 측정의 검색·초안·검증 단계 조립. 저장 없이 서비스 흐름을 따른다."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from aml_ai.shared.db import end_read
from aml_ai.shared.schemas.str import Facts, RevisedNarrativeSection
from aml_ai.str.application.draft_rewrite import NarrativeRewriter, try_rewrite
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE, JUDGE_VOTES, PATH_RULE_KIND
from aml_ai.str.domain.fact_keys import fact_keys
from aml_ai.str.domain.verification import run_code_checks
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.judge import Judge
from aml_ai.str.infrastructure.narrative_generator import NarrativeGenerator
from aml_ai.str.infrastructure.reference_snippet import prompt_references
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.stability_support import Call, RunRecord, section_digest

JUDGE_PROMPT = "judge_v3"


def transaction_ids(facts: Facts) -> list[int]:
    """입출금·내부·간접·경로 등 facts 전체의 거래 ID 합집합을 구한다."""

    def collect(value: Any) -> set[int]:
        if isinstance(value, dict):
            ids = set(value.get("transaction_ids", []))
            for nested in value.values():
                ids.update(collect(nested))
            return ids
        if isinstance(value, list):
            return {tid for nested in value for tid in collect(nested)}
        return set()

    return sorted(collect(facts.model_dump()))


def retrieve(facts: Facts, settings: Any, embedder: Any, session: Any) -> tuple[list, str]:
    """검색 실패 시 트랜잭션을 정리하고, 성공 시 연결을 즉시 반납한다."""
    try:
        refs = Retriever(session, embedder, enabled=True).retrieve(facts)
        end_read(session)
    except Exception:
        session.rollback()
        return [], "failed"
    return prompt_references(settings.narrative_prompt, refs), "ok" if refs else "empty"


def draft_inputs(facts: Facts, refs: list, deadline: float, settings: Any) -> dict[str, Any]:
    """생성과 고쳐 쓰기가 공유하는 입력·근거 범위를 만든다."""
    return {
        "facts": facts,
        "facts_masked": masking.mask_for_llm(facts),
        "fact_keys": list(fact_keys(facts)),
        "examples": FewshotStore(prompt_name=settings.narrative_prompt).pick_examples(facts.typology),
        "references": refs,
        "notes": None,
        "alert_rule_id": next((rule for rule, kind in PATH_RULE_KIND.items() if kind == facts.typology), ""),
        "evidence_scope": transaction_ids(facts),
        "deadline": deadline,
    }


def generate(inputs: dict[str, Any], llm: Any, settings: Any) -> Any:
    """서비스와 같은 생성기를 사용한다. 초안 전체가 같은 마감 시간을 쓴다."""
    kwargs = {
        k: inputs[k] for k in ("facts_masked", "fact_keys", "examples", "references", "notes", "deadline")
    }
    return NarrativeGenerator(llm, settings, prompt_name=settings.narrative_prompt).generate(**kwargs)


def rewrite(inputs: dict[str, Any], gen: Any, narrative: list, llm: Any, settings: Any) -> Any:
    """초안 평가자는 단일 투표·스키마 재시도 0회로 조립한다."""
    return try_rewrite(
        **inputs,
        settings=settings,
        original_gen=gen,
        original_narrative=narrative,
        judge=Judge(llm, settings, prompt_name=JUDGE_PROMPT, schema_retry=0, clock=time.monotonic),
        rewriter=NarrativeRewriter(llm, settings, clock=time.monotonic),
        clock=time.monotonic,
    )


def generation_call(gen: Any, original: Any = None) -> Call:
    """고쳐 쓰기 합산 결과에서는 첫 생성 사용량을 빼서 중복을 막는다."""
    kind = "rewrite" if original is not None else "generate"
    values = [
        getattr(gen, k) - (getattr(original, k) if original else 0)
        for k in ("tokens_in", "tokens_out", "latency_ms")
    ]
    return Call(kind, *values)


def rewrite_calls(meta: Any, final_gen: Any, first_gen: Any) -> list[Call]:
    """초안 평가자와 시도된 재작성의 사용량을 기록한다. 미적용도 토큰 차액이 양수면 포함한다."""
    calls = []
    values = (meta.critique_tokens_in, meta.critique_tokens_out, meta.critique_latency_ms)
    if all(value is not None for value in values):
        calls.append(Call("critique", *values))
    if meta.attempted:
        call = generation_call(final_gen, first_gen)
        if call.tokens_in + call.tokens_out > 0:
            calls.append(call)
    return calls


def inspect_body(
    record: RunRecord, facts: Facts, narrative: list, scope: list[int], *, first: bool
) -> RunRecord:
    """검사 이름·사유와 최종 해시·길이만 남긴다."""
    hashes, chars, numbers = section_digest({s.section.value: s.text for s in narrative})
    failures = [
        f"{c.check.value}:{c.reason.value}" for c in run_code_checks(facts, narrative, scope) if not c.match
    ]
    field = "code_failures_first" if first else "code_failures_final"
    return replace(
        record, section_hashes=hashes, section_chars=chars, number_set_hash=numbers, **{field: failures}
    )


def verify(record: RunRecord, inputs: dict[str, Any], narrative: list, llm: Any, settings: Any) -> RunRecord:
    """코드 실패 시 평가자 호출을 막고, 예외 이름·부분 메타를 보존한다. 예외 메시지는 남기지 않는다."""
    if record.code_failures_final:
        return replace(record, final_status="CODE_FAILED")
    try:
        revised = [RevisedNarrativeSection.model_validate(s.model_dump()) for s in narrative]
        judge = Judge(llm, settings, prompt_name=JUDGE_PROMPT, votes=JUDGE_VOTES)
        result = judge.run(
            facts_masked=inputs["facts_masked"],
            narrative=revised,
            fact_keys=inputs["fact_keys"],
            deadline=time.monotonic() + settings.verify_budget_s,
        )
    except Exception as exc:
        meta = getattr(exc, "judge_meta", None)
        if meta is not None:
            record.calls.append(Call("judge", meta.tokens_in, meta.tokens_out, meta.latency_ms))
        return replace(record, final_status="VERIFY_UNAVAILABLE", error=type(exc).__name__)
    meta = result.meta
    record.calls.append(Call("judge", meta.tokens_in, meta.tokens_out, meta.latency_ms))
    scores = {c.check.value: c.score for c in result.checks}
    status = "PASSED" if all(s >= JUDGE_PASS_SCORE for s in scores.values()) else "LLM_FAILED"
    return replace(record, judge_scores=scores, final_status=status)
