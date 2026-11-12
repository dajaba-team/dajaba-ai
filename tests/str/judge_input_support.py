"""SCRUM-207 — 판정 흔들림 측정용 Judge 입력 조립 helper (지시서 ★A 1 조건 2 — 공용 로더 분리).

`tests/str/judge_stability_live.py` 와 `injection_live_*` 가 공용으로 쓴다. facts·narrative·user 조립은
실제 draft_service·verify_service 의 흐름 그대로 (저장·전송 왕복 포함 비교는 judge_stability_paths).
"""

from __future__ import annotations

import json
from pathlib import Path

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import LlmClient, RecordedLlmClient
from aml_ai.shared.schemas.str import Facts, NarrativeSection, RevisedNarrativeSection
from aml_ai.shared.schemas.str.narrative_version import llm_output_model
from aml_ai.str.domain import masking
from aml_ai.str.domain.fact_keys import attach_evidence, fact_keys
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.judge import render_judge_user
from aml_ai.str.infrastructure.narrative_generator import load_prompt, render_user

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests/str/fixtures"

# SCRUM-207 — 평가자 흔들림 측정 본문 둘(지시서 1단계).
CASE_FIXTURES: dict[int, str] = {
    12: "facts_fan_in.json",  # 정상 초안 — 기준 본문
    23: "facts_cycle_nopaths.json",  # CYCLE + paths=None (SCRUM-147)
}


def facts_for_case(case: int) -> Facts:
    """SCRUM-207 — 측정 본문별 facts 로더."""
    name = CASE_FIXTURES[case]
    return Facts.model_validate(json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def original_narrative_for_case(case: int, *, llm: LlmClient | None = None) -> list[NarrativeSection]:
    """SCRUM-207 — case 의 "고치기 전 원본" narrative (draft_rewrite 초안 안 경로 입력과 동형).

    녹화 재생으로 생성 결과를 얻어 attach_evidence 로 cites·evidence_ids 를 채운다. llm 기본값은
    RecordedLlmClient — dry-run 과 live 모두 녹화된 생성본을 쓰므로 호출 0. narrative_v2 전제.
    """
    settings = get_settings()
    client = llm if llm is not None else RecordedLlmClient(settings.recorded_dir)
    facts = facts_for_case(case)
    facts_masked = masking.mask_for_llm(facts)
    keys = list(fact_keys(facts).keys())
    examples = FewshotStore(prompt_name="narrative_v2").pick_examples(facts.typology)
    system, user_tpl = load_prompt("narrative_v2")
    user = render_user(
        user_tpl,
        facts_masked=facts_masked,
        fact_keys=keys,
        examples=examples,
        references=[],
        notes=None,
    )
    res = client.complete_json(
        system=system,
        user=user,
        model=settings.llm_model_generate or "recorded",
        max_tokens=2000,
        tag="narrative_v2",
    )
    parsed = llm_output_model("narrative_v2").model_validate_json(res.text)
    narrative = [
        NarrativeSection(section=s.section, text=s.text, cites=list(s.cites)) for s in parsed.narrative
    ]
    return attach_evidence(narrative, facts)


def render_judge_user_for(
    facts: Facts,
    narrative: list[NarrativeSection] | list[RevisedNarrativeSection],
    prompt_name: str,
) -> tuple[str, str, list[str]]:
    """SCRUM-207 — Judge.run 이 조립하는 (system, user, fact_keys) 를 그대로 재현.

    verify_service._decide·draft_rewrite._run_judge 둘 다 같은 조립 규칙을 쓴다. 두 경로가 **같은 본문**
    이면 user 문자열이 같아야 한다(docs/str/06 "두 경로 입력 맞추기"). 다르면 입력 차이가 있는 것.
    """
    system, user_tpl = load_prompt(prompt_name)
    keys = list(fact_keys(facts).keys())
    sections_list = [s.section.value for s in narrative]
    user = render_judge_user(
        user_tpl,
        facts_masked=masking.mask_for_llm(facts),
        narrative=narrative,
        fact_keys=keys,
        request_sections=sections_list,
    )
    return system, user, keys


def facts_as_json_roundtrip(facts: Facts) -> Facts:
    """generation_repository.finish 저장값 ↔ load_draft 복원값 왕복 (SCRUM-207 입력 차이 측정용)."""
    return Facts.model_validate(facts.model_dump(mode="json"))


def narrative_to_revised(narrative: list[NarrativeSection]) -> list[RevisedNarrativeSection]:
    """초안 응답 narrative → verify 요청 narrative 왕복 (model_dump(mode='json') → model_validate)."""
    return [RevisedNarrativeSection.model_validate(s.model_dump(mode="json")) for s in narrative]
