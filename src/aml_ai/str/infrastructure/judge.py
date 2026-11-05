"""평가자 LLM — 코드 검증 통과 뒤에만. comment 먼저, score 나중 (docs/str/06, 05).

v2 (SCRUM-61, 11/5 활성): 입력에 FACT_KEYS, 출력에 섹션별 cites. sections 집합이 요청과 다르면
`LlmInvalidOutput` 로 기존 1회 재시도(SCRUM-92) → 또 실패면 호출 측(`verify_service`)이 VERIFY_UNAVAILABLE.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.llm_client import LlmClient, LlmResult
from aml_ai.shared.schemas.str import (
    JudgeMeta,
    JudgeOut,
    JudgeOutV2,
    LlmCheck,
    NarrativeRefLlm,
    NarrativeSection,
    llm_output_model,
)
from aml_ai.str.domain.constants import JUDGE_MAX_TOKENS, JUDGE_PROMPT, JUDGE_SCHEMA_RETRY
from aml_ai.str.infrastructure.narrative_generator import load_prompt

log = logging.getLogger(__name__)


def judge_model_decision(settings: Settings) -> tuple[str, str | None]:
    if settings.ai_llm_mock:
        return settings.llm_model_generate, None
    if not settings.llm_model_judge:
        return settings.llm_model_generate, "EMPTY"
    if settings.llm_model_judge == settings.llm_model_generate:
        return settings.llm_model_judge, "SAME"
    return settings.llm_model_judge, None


def render_judge_user(
    template: str,
    *,
    facts_masked: dict[str, Any],
    narrative: list[NarrativeSection],
    fact_keys: list[str] | None,
    request_sections: list[str] | None,
) -> str:
    """judge_v1·v2 공용 — 녹화 도구와 같은 함수로 user 문자열을 만들어야 녹화 키가 맞음.

    v1 템플릿은 FACT_KEYS·request_sections 블록이 없어 replace 가 no-op. v2 는 둘 다 넣는다.
    FACT_KEYS 모양은 생성기(`narrative_generator.render_user`)와 같게 `"\\n".join(keys) or "(없음)"`.
    """
    return (
        template.replace("{{facts_json}}", json.dumps(facts_masked, ensure_ascii=False, indent=2))
        .replace(
            "{{narrative_json}}",
            json.dumps({"narrative": [s.model_dump() for s in narrative]}, ensure_ascii=False, indent=2),
        )
        .replace("{{fact_keys}}", "\n".join(fact_keys or []) or "(없음)")
        .replace("{{request_sections}}", "\n".join(request_sections or []) or "(없음)")
    )


@dataclass(frozen=True)
class JudgeResult:
    checks: list[LlmCheck]
    meta: JudgeMeta
    sections: list[NarrativeRefLlm] = field(default_factory=list)


class Judge:
    def __init__(
        self,
        llm: LlmClient,
        settings: Settings,
        prompt_name: str = JUDGE_PROMPT,
        *,
        request_sections: list[str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._llm = llm
        self._s = settings
        self._clock = clock
        self.prompt_version = prompt_name
        self._system, self._user_tpl = load_prompt(prompt_name)
        self._request_sections = list(request_sections) if request_sections is not None else None

    def run(
        self,
        facts_masked: dict[str, Any],
        narrative: list[NarrativeSection],
        *,
        deadline: float | None = None,
        fact_keys: list[str] | None = None,
    ) -> JudgeResult:
        """스키마 실패만 예산 안에서 재시도하고 소비한 토큰을 합산한다."""
        request_sections = self._request_sections or [s.section.value for s in narrative]
        user = render_judge_user(
            self._user_tpl,
            facts_masked=facts_masked,
            narrative=narrative,
            fact_keys=fact_keys,
            request_sections=request_sections,
        )
        model, _ = judge_model_decision(self._s)
        return self._call_with_retry(user, model, request_sections, deadline)

    def _call_with_retry(
        self, user: str, model: str, request_sections: list[str], deadline: float | None
    ) -> JudgeResult:
        results: list[LlmResult] = []
        for attempt in range(JUDGE_SCHEMA_RETRY + 1):
            calls = attempt + 1  # SCRUM-144 — 보낸 호출 수(실패 포함)
            try:
                res = self._llm.complete_json(
                    system=self._system,
                    user=user,
                    model=model,
                    max_tokens=JUDGE_MAX_TOKENS,
                    tag=self.prompt_version,
                )
            except Exception as exc:
                # SCRUM-144 — 2차+ complete_json 이 예외로 끝나면 앞선 1차 토큰을 보존.
                # 첫 호출 자체 예외면 results 비어 judge_meta 안 붙음(지금 동작 그대로).
                if results:
                    exc.judge_meta = self._meta(results, calls=calls)
                raise
            results.append(res)
            meta = self._meta(results, calls=calls)
            try:
                checks, sections = self._parse(res.text, request_sections)
            except LlmInvalidOutput as exc:
                log.warning("judge_invalid_output", extra={"reason": type(exc).__name__})
                exc.judge_meta = meta
                if attempt == JUDGE_SCHEMA_RETRY or (
                    deadline is not None and deadline - self._clock() < self._s.llm_timeout_s
                ):
                    raise
            else:
                return JudgeResult(checks=checks, meta=meta, sections=sections)
        raise AssertionError("judge retry loop exhausted")

    def _meta(self, results: list[LlmResult], *, calls: int) -> JudgeMeta:
        """SCRUM-144 — `attempts` = 보낸 호출 수(`calls`, 실패 포함).

        `tokens·latency` 는 `results` 합 — 결과 받은 호출만. 실패 호출 지연은 안 셈(`09`).
        """
        return JudgeMeta(
            llm_model=results[-1].model,
            prompt_version=self.prompt_version,
            tokens_in=sum(r.tokens_in for r in results),
            tokens_out=sum(r.tokens_out for r in results),
            latency_ms=sum(r.latency_ms for r in results),
            attempts=calls,
        )

    def _parse(self, text: str, request_sections: list[str]) -> tuple[list[LlmCheck], list[NarrativeRefLlm]]:
        model = llm_output_model(self.prompt_version)
        try:
            out = model.model_validate_json(text)
        except (ValidationError, ValueError) as exc:
            raise LlmInvalidOutput("judge output failed schema") from exc
        if isinstance(out, JudgeOutV2):
            if {s.section.value for s in out.sections} != set(request_sections):
                raise LlmInvalidOutput("judge sections mismatch request")
            return out.checks, out.sections
        assert isinstance(out, JudgeOut)
        return out.checks, []
