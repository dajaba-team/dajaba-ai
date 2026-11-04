"""평가자 LLM — 코드 검증 통과 뒤에만. comment 먼저, score 나중 (docs/str/06, 05)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.llm_client import LlmClient, LlmResult
from aml_ai.shared.schemas.str import JudgeMeta, JudgeOut, LlmCheck, NarrativeSection
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


@dataclass(frozen=True)
class JudgeResult:
    checks: list[LlmCheck]
    meta: JudgeMeta


class Judge:
    def __init__(
        self,
        llm: LlmClient,
        settings: Settings,
        prompt_name: str = JUDGE_PROMPT,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._llm = llm
        self._s = settings
        self._clock = clock
        self.prompt_version = prompt_name
        self._system, self._user_tpl = load_prompt(prompt_name)

    def run(
        self,
        facts_masked: dict[str, Any],
        narrative: list[NarrativeSection],
        *,
        deadline: float | None = None,
    ) -> JudgeResult:
        """스키마 실패만 예산 안에서 재시도하고 소비한 토큰을 합산한다."""
        user = self._user_tpl.replace(
            "{{facts_json}}", json.dumps(facts_masked, ensure_ascii=False, indent=2)
        ).replace(
            "{{narrative_json}}",
            json.dumps({"narrative": [s.model_dump() for s in narrative]}, ensure_ascii=False, indent=2),
        )
        model, _ = judge_model_decision(self._s)
        results: list[LlmResult] = []
        for attempt in range(JUDGE_SCHEMA_RETRY + 1):
            res = self._llm.complete_json(
                system=self._system,
                user=user,
                model=model,
                max_tokens=JUDGE_MAX_TOKENS,
                tag=self.prompt_version,
            )
            results.append(res)
            meta = self._meta(results)
            try:
                checks = self._parse(res.text)
            except LlmInvalidOutput as exc:
                log.warning("judge_invalid_output", extra={"reason": type(exc).__name__})
                exc.judge_meta = meta
                if attempt == JUDGE_SCHEMA_RETRY or (
                    deadline is not None and deadline - self._clock() < self._s.llm_timeout_s
                ):
                    raise
            else:
                return JudgeResult(checks=checks, meta=meta)
        raise AssertionError("judge retry loop exhausted")

    def _meta(self, results: list[LlmResult]) -> JudgeMeta:
        return JudgeMeta(
            llm_model=results[-1].model,
            prompt_version=self.prompt_version,
            tokens_in=sum(r.tokens_in for r in results),
            tokens_out=sum(r.tokens_out for r in results),
            latency_ms=sum(r.latency_ms for r in results),
            attempts=len(results),
        )

    @staticmethod
    def _parse(text: str) -> list[LlmCheck]:
        try:
            return JudgeOut.model_validate_json(text).checks
        except (ValidationError, ValueError) as exc:
            raise LlmInvalidOutput("judge output failed schema") from exc
