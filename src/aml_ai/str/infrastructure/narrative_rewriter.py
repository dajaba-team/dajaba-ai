"""SCRUM-147 — rewrite_v1 프롬프트 조립 + LLM 호출 (docs/str/05 rewrite_v1).

try_rewrite(draft_rewrite.py) 가 이 모듈의 함수·클래스만 쓴다 — 상위 분기 로직은 draft_rewrite.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.llm_client import LlmClient
from aml_ai.shared.schemas.str import Facts, JudgeOutV2, Reference, llm_output_model
from aml_ai.shared.schemas.str.narrative import NarrativeSectionBase
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE, NARRATIVE_MAX_TOKENS, PATH_RULE_KIND
from aml_ai.str.domain.models import Example, GenerationResult
from aml_ai.str.infrastructure.narrative_generator import (
    _check_cites_in_scope,
    load_prompt,
    render_user,
)

PATHS_NOTICE_TEMPLATE = (
    "10a. 이 경보는 경로형 룰이지만 FACTS의 paths가 확인되지 않았습니다. "
    "유형은 facts.typology 값으로 밝히되, "
    '그 유형의 경로 형태는 "~형태가 의심되나 경로는 확인 필요"처럼 의심 표현으로만 쓰고, '
    "고리 순서·이체 횟수·거친 계좌 수는 쓰지 않습니다."
)


def build_paths_notice(alert_rule_id: str, facts: Facts) -> str:
    """경보가 경로형 룰이고 paths 가 확인 안 됐을 때만 안내 블록 반환. 그 밖 ''."""
    if alert_rule_id not in PATH_RULE_KIND:
        return ""
    if facts.paths is not None and getattr(facts.paths, "status", None) == "VERIFIED":
        return ""
    return PATHS_NOTICE_TEMPLATE


def assemble_critique(judge_out: JudgeOutV2, pass_score: int) -> str:
    """평가자가 낸 순서 그대로, score < pass_score 항목만 줄로. 통과 항목은 뺌."""
    lines: list[str] = []
    for c in judge_out.checks:
        if c.score < pass_score:
            lines.append(f"- {c.check.value} (score {c.score}): {c.comment}")
    return "\n".join(lines)


def serialize_original_narrative(narrative: list[NarrativeSectionBase]) -> str:
    """{section, text, cites} 만 JSON — evidence_ids 제거 (05 "LLM에 거래 ID 안 줌" 유지)."""
    items = [s.model_dump(include={"section", "text", "cites"}, mode="json") for s in narrative]
    return json.dumps({"narrative": items}, ensure_ascii=False, indent=2)


def render_rewrite_prompts(
    *,
    facts_masked: dict[str, Any],
    fact_keys: list[str],
    examples: list[Example],
    references: list[Reference],
    notes: str | None,
    original_narrative: list[NarrativeSectionBase],
    critique: JudgeOutV2,
    paths_notice: str,
) -> tuple[str, str]:
    """(system, user) 반환. system 에 paths_notice, user 에 original_narrative·critique 블록."""
    system_tpl, user_tpl = load_prompt("rewrite_v1")
    system = system_tpl.replace("{{paths_notice}}", paths_notice)
    user = render_user(
        user_tpl,
        facts_masked=facts_masked,
        fact_keys=fact_keys,
        notes=notes,
        references=references,
        examples=examples,
    )
    user = user.replace("{{original_narrative}}", serialize_original_narrative(original_narrative))
    user = user.replace("{{critique}}", assemble_critique(critique, JUDGE_PASS_SCORE))
    return system, user


class NarrativeRewriter:
    """rewrite_v1 LLM 호출. 스키마 실패 재생성 0회 (SCRUM-147, 시간 예산)."""

    def __init__(
        self,
        llm: LlmClient,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._llm = llm
        self._s = settings
        self._clock = clock
        self.prompt_version = "rewrite_v1"

    def _parse(self, res, fact_keys: list[str]) -> GenerationResult:  # type: ignore[no-untyped-def]
        try:
            out = llm_output_model(self.prompt_version).model_validate_json(res.text)
            _check_cites_in_scope(out, fact_keys)
        except (ValidationError, ValueError) as exc:
            # SCRUM-147 — usage 받은 스키마 실패는 호출자가 토큰 합산할 수 있게 LlmResult 첨부.
            new_exc = LlmInvalidOutput("rewrite failed schema validation")
            new_exc.llm_result = res
            raise new_exc from exc
        return GenerationResult(
            narrative=out.narrative,
            llm_model=res.model,
            prompt_version=self.prompt_version,
            tokens_in=res.tokens_in,
            tokens_out=res.tokens_out,
            latency_ms=res.latency_ms,
        )

    def rewrite(self, *, deadline: float, **kw: Any) -> GenerationResult:  # noqa: ARG002
        """kw 는 render_rewrite_prompts 의 키워드 인자 — facts_masked·fact_keys·examples·references·notes·original_narrative·critique·paths_notice."""
        system, user = render_rewrite_prompts(**kw)
        res = self._llm.complete_json(
            system=system,
            user=user,
            model=self._s.llm_model_generate,
            max_tokens=NARRATIVE_MAX_TOKENS,
            tag=self.prompt_version,
        )
        return self._parse(res, kw["fact_keys"])
