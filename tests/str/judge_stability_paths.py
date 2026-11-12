"""SCRUM-207 — 측정 도구 경로 입력 조립 (judge_stability_live.py 에서 분리, 손 실행 X)."""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass

from aml_ai.shared.schemas.str import Facts, RevisedNarrativeSection
from aml_ai.str.domain import masking
from aml_ai.str.domain.fact_keys import fact_keys as domain_fact_keys
from aml_ai.str.infrastructure.judge import render_judge_user
from aml_ai.str.infrastructure.narrative_generator import load_prompt
from tests.str.judge_input_support import (
    facts_for_case,
    original_narrative_for_case,
)


@dataclass(frozen=True)
class PathInput:
    """두 경로 한 쪽의 조립 결과 — Judge.run 입력 그 자체."""

    system: str
    user: str
    fact_keys: list[str]
    user_sha256: str
    label: str  # "draft_inside" | "verify"
    source: dict[str, str]  # 입력 조각 → "파일:행 — 설명"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# 각 경로가 입력을 만드는 코드 줄 (develop aa0bf54, 2026-11-12) — ★B 표 재료.
SOURCE_DRAFT: dict[str, str] = {
    "facts": "draft_service.py:101 — build_facts(req.to_facts_input(), txs, subject)",
    "facts_masked": "draft_service.py:102 — masking.mask_for_llm(facts)",
    "fact_keys": "draft_service.py:108 — list(fact_keys_domain.fact_keys(facts).keys())",
    "narrative": "draft_service.py:112 — attach_evidence(gen.narrative, facts)  # NarrativeSection",
    "judge_call": "draft_rewrite.py:97-99 — ctx.judge.run(ctx.facts_masked, ctx.original_narrative, deadline=ctx.deadline, fact_keys=ctx.fact_keys)",  # noqa: E501
}
SOURCE_VERIFY: dict[str, str] = {
    "facts": "generation_repository.py:143,186 — facts.model_dump(mode='json') → Facts.model_validate(row.facts) 왕복",  # noqa: E501
    "facts_masked": "verify_service.py:119 — masking.mask_for_llm(draft.facts)",
    "fact_keys": "verify_service.py:120,123 — list(domain_fact_keys(draft.facts).keys())",
    "narrative": "verify.py:136 — list[RevisedNarrativeSection]  # 백엔드가 초안 응답 narrative 를 그대로 verify 요청으로 (NarrativeSection.model_dump(mode='json') → RevisedNarrativeSection.model_validate 왕복)",  # noqa: E501
    "judge_call": "verify_service.py:122-124 — self.judge.run(masking.mask_for_llm(draft.facts), req.narrative, deadline=deadline, fact_keys=list(keys.keys()))",  # noqa: E501
}


def build_draft_path(case: int, prompt_name: str) -> PathInput:
    """초안 안 경로 — draft_service._generate → draft_rewrite._run_judge 입력 그대로."""
    facts = facts_for_case(case)
    narrative = original_narrative_for_case(case)
    facts_masked = masking.mask_for_llm(facts)
    keys = list(domain_fact_keys(facts).keys())
    system, user_tpl = load_prompt(prompt_name)
    user = render_judge_user(
        user_tpl,
        facts_masked=facts_masked,
        narrative=narrative,
        fact_keys=keys,
        request_sections=[s.section.value for s in narrative],
    )
    return PathInput(system, user, keys, _sha(user), "draft_inside", SOURCE_DRAFT)


def build_verify_path(case: int, prompt_name: str) -> PathInput:
    """검증 경로 — 저장·읽기 왕복 + 초안 응답→VerifyRequest 왕복까지 흉내."""
    facts_before = facts_for_case(case)
    stored_facts_json = facts_before.model_dump(mode="json")
    facts = Facts.model_validate(stored_facts_json)
    narrative_generated = original_narrative_for_case(case)
    narrative = [
        RevisedNarrativeSection.model_validate(s.model_dump(mode="json")) for s in narrative_generated
    ]
    facts_masked = masking.mask_for_llm(facts)
    keys = list(domain_fact_keys(facts).keys())
    system, user_tpl = load_prompt(prompt_name)
    user = render_judge_user(
        user_tpl,
        facts_masked=facts_masked,
        narrative=narrative,
        fact_keys=keys,
        request_sections=[s.section.value for s in narrative],
    )
    return PathInput(system, user, keys, _sha(user), "verify", SOURCE_VERIFY)


def build_path_inputs(case: int, prompt_name: str) -> tuple[PathInput, PathInput]:
    """두 경로 입력을 **실제 저장·왕복** 그대로 조립 — 같은 본문이 같은 user 를 만드는지 측정."""
    a = build_draft_path(case, prompt_name)
    b = build_verify_path(case, prompt_name)
    assert a.system == b.system, "same prompt_name should give same system"
    return a, b


def first_diff_block(a: str, b: str, context: int = 3) -> str | None:
    """첫 번째 다른 줄 앞뒤 context 줄 — 본문 전체 금지 (지시서)."""
    if a == b:
        return None
    a_lines = a.splitlines()
    b_lines = b.splitlines()
    sm = difflib.SequenceMatcher(a=a_lines, b=b_lines, autojunk=False)
    for tag, i1, _i2, j1, _j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        lo_a = max(0, i1 - context)
        lo_b = max(0, j1 - context)
        hi_a = min(len(a_lines), i1 + context + 1)
        hi_b = min(len(b_lines), j1 + context + 1)
        block = [f"--- draft path (lines {lo_a}-{hi_a}) ---"]
        block.extend(a_lines[lo_a:hi_a])
        block.append(f"+++ verify path (lines {lo_b}-{hi_b}) +++")
        block.extend(b_lines[lo_b:hi_b])
        return "\n".join(block)
    return None
