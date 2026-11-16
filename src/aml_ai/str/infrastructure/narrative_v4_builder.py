"""narrative_v4 — 코드 조립(LLM 호출 0) (docs/str/05 narrative_v4, str/03 7v4).

사전 검사 → 플래그 → 슬롯 → 카탈로그 후보 → 순서 목록(Plan) → 조립. `NarrativeGenerator` 가 v4 일 때만 부른다.
편집자 Plan 을 받으면 검증하고, 실패면 코드 Plan 으로 완성(v2 자동 전환 없음). 로그에는 칸 이름·코드값·사유 코드만.
"""

from __future__ import annotations

import logging
from typing import Any

from aml_ai.shared.errors import NarrativeAssemblyFailed
from aml_ai.shared.schemas.str import LlmNarrativeSection, Reference
from aml_ai.str.domain.catalog_types import render_context
from aml_ai.str.domain.constants_v4 import NARRATIVE_V4, V4_CODE_MODEL
from aml_ai.str.domain.derived_flags import derive_flags
from aml_ai.str.domain.display_labels_check import Labels, missing_labels
from aml_ai.str.domain.display_slots import build_slots
from aml_ai.str.domain.models import GenerationResult
from aml_ai.str.domain.narrative_assembly import AssemblyTooLong, assemble
from aml_ai.str.domain.narrative_plan import Plan, candidates, default_plan, validate_plan

log = logging.getLogger(__name__)


def generate_v4(
    facts_masked: dict[str, Any], labels: Labels, references: list[Reference], notes: str | None
) -> GenerationResult:
    """LLM 호출 0 — references·메모는 본문에 안 씀(05). generation_meta 는 ★A-8 값(code·토큰 0·few_shot [])."""
    return GenerationResult(
        narrative=build_v4(facts_masked, labels),
        llm_model=V4_CODE_MODEL,
        prompt_version=NARRATIVE_V4,
        tokens_in=0,
        tokens_out=0,
        latency_ms=0,
        request_payload={
            "few_shot_ids": [],
            "reference_ids": [r.doc_id for r in references],
            "has_notes": bool(notes),
        },
    )


def build_v4(
    facts_masked: dict[str, Any], labels: Labels, *, editor_plan: Plan | None = None
) -> list[LlmNarrativeSection]:
    missing = missing_labels(facts_masked, labels)
    if missing:
        log.error(
            "display_label_missing",
            extra={"fields": [f for f, _ in missing], "codes": [c for _, c in missing]},
        )
        raise NarrativeAssemblyFailed("display label missing")
    flags = derive_flags(facts_masked)
    slots = build_slots(facts_masked, labels, flags)
    cands = candidates(facts_masked, flags)
    plan = _choose_plan(editor_plan, cands)
    try:
        return assemble(slots, plan, cands, render_context(facts_masked, labels))
    except AssemblyTooLong as exc:
        log.error("narrative_v4_too_long", extra={"section": exc.section.value, "length": exc.length})
        raise NarrativeAssemblyFailed("assembled section too long") from None


def _choose_plan(editor_plan: Plan | None, cands: Any) -> Plan:
    if editor_plan is None:
        return default_plan(cands)
    problems = validate_plan(editor_plan, cands)
    if problems:
        log.warning("narrative_v4_plan_rejected", extra={"reasons": problems})
        return default_plan(cands)
    return editor_plan
