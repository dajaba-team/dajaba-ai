"""SCRUM-147 추가 검토 — draft 경로 StubLlm 호출 상한 ≤ 4 (서비스 레벨).

generator + judge + rewriter 를 같은 StubLlm 으로 조립. 시나리오:
  ① generator 첫 호출 스키마 실패 (not-json)
  ② generator 재시도 성공 (녹화된 narrative_v2 본문)
  ③ 평가자 스키마 실패 (not-json) → critique_error → rewriter 호출 0

→ len(stub.calls) == 3. 평가자 뒤 추가 응답(4번째)이 있어도 호출 자체가 안 나감.

draft_service.build 에서 `schema_retry=0` 을 빼면 평가자가 1회 더 호출돼 len==4 가 되어 이 테스트가 깨진다.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.application.draft_rewrite import NarrativeRewriter, try_rewrite
from aml_ai.str.domain import fact_keys as fact_keys_domain
from aml_ai.str.domain import masking
from aml_ai.str.domain.fact_keys import attach_evidence
from aml_ai.str.infrastructure.judge import Judge
from aml_ai.str.infrastructure.narrative_generator import NarrativeGenerator
from tests.str.judge_support import StubCall, StubLlm

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_FAN_IN = REPO_ROOT / "tests" / "str" / "fixtures" / "facts_fan_in.json"
NARRATIVE_V2_REC = REPO_ROOT / "tests" / "str" / "recorded" / "narrative_v2" / "a976ae216c7fb1bb.json"


def _generator_phase(stub: StubLlm, settings, facts: Facts):  # type: ignore[no-untyped-def]
    facts_masked = masking.mask_for_llm(facts)
    fact_keys = list(fact_keys_domain.fact_keys(facts).keys())
    deadline = time.monotonic() + settings.draft_budget_s
    generator = NarrativeGenerator(stub, settings, "narrative_v2")
    gen = generator.generate(
        facts_masked, fact_keys, examples=[], references=[], notes=None, deadline=deadline
    )
    return gen, attach_evidence(gen.narrative, facts), facts_masked, fact_keys, deadline


def test_draft_call_cap_three_when_generator_retries_and_judge_fails_schema() -> None:
    narrative_text = json.loads(NARRATIVE_V2_REC.read_text())["text"]
    stub = StubLlm(
        call_specs=[
            StubCall(text="not-json"),  # ① generator 스키마 실패
            StubCall(text=narrative_text),  # ② generator 재시도 성공
            StubCall(text="not-judge-json"),  # ③ 평가자 스키마 실패
            StubCall(text=narrative_text),  # 4번째 — 호출돼선 안 됨 (가드)
        ]
    )
    get_settings.cache_clear()
    settings = get_settings()
    facts = Facts.model_validate(json.loads(FIXTURE_FAN_IN.read_text()))
    gen, narrative, facts_masked, fact_keys, deadline = _generator_phase(stub, settings, facts)
    assert len(stub.calls) == 2  # generator 스키마 재시도 1회 포함

    result = try_rewrite(
        settings=settings,
        facts=facts,
        facts_masked=facts_masked,
        fact_keys=fact_keys,
        examples=[],
        references=[],
        notes=None,
        alert_rule_id="R01_LARGE_CASH",  # 경로형 아님 → paths_notice 빈 문자열
        evidence_scope=[1, 2, 3],
        original_narrative=narrative,
        original_gen=gen,
        judge=Judge(stub, settings, prompt_name="judge_v3", schema_retry=0),
        rewriter=NarrativeRewriter(stub, settings),
        clock=time.monotonic,
        deadline=deadline,
    )

    assert result is not None
    meta, _, _ = result
    assert meta.skipped_reason == "critique_error"
    # SCRUM-147 추가 검토 — Judge(schema_retry=0) 전제. generator 2 + judge 1 + rewriter 0 = 3.
    # draft_service.build 에서 schema_retry=0 을 빼면 judge 2번 → 4가 되어 이 테스트가 깨진다.
    assert len(stub.calls) == 3
