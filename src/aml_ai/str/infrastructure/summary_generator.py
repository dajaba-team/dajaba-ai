"""요약 생성기(`SUMMARY_PROMPT`, 지금 summary_v2) — 프롬프트 조립 → LLM → SummaryOut 검증. 재생성 1회 (SCRUM-129).

SCRUM-340 — 입력은 버전별(`summary_prompt_input`): v2 만 본·few-shot FACTS 금액 칸을 표기 문자열로.

스키마 실패면 남은 예산 안에서 1회 재생성. 두 번 다 실패면 `LlmInvalidOutput`. 코드 검사 실패는
호출 측(`summary_service`)이 다시 호출해 재생성한다 — 이 모듈은 "스키마" 재생성만 관리.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.infrastructure.llm_client import LlmClient
from aml_ai.shared.schemas.str import Facts, SummaryOut
from aml_ai.str.domain.constants import SCHEMA_RETRY, SUMMARY_MAX_TOKENS, SUMMARY_PROMPT
from aml_ai.str.domain.display_labels_check import Labels
from aml_ai.str.domain.models import SummaryExample, SummaryGenerationResult
from aml_ai.str.infrastructure.narrative_generator import load_prompt
from aml_ai.str.infrastructure.summary_prompt_input import (  # noqa: F401 — 기존 import 자리(서비스·테스트) 유지
    FEWSHOT_ROOT,
    SummaryInput,
    labels_for,
    load_summary_fewshot,
    prepare_summary_input,
    render_summary_user,
)

log = logging.getLogger(__name__)


class SummaryGenerator:
    """프롬프트·LLM 호출·스키마 검증·재생성 1회 (SCRUM-129)."""

    def __init__(
        self,
        llm: LlmClient,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.monotonic,
        labels: Labels | None = None,
        prompt: str | None = None,
    ) -> None:
        self._llm = llm
        self._s = settings
        self._clock = clock
        self.prompt_version = prompt or SUMMARY_PROMPT  # 기본 = 상수(되돌림은 상수 한 줄, 검토 1 M4)
        # 표기 사전은 버전을 정한 뒤 v2 일 때만(초안 v4 와 같은 사전, 검토 2 M6)
        self.labels = labels if labels is not None else labels_for(self.prompt_version)
        self._system, self._user_tpl = load_prompt(self.prompt_version)

    def prepare(self, facts: Facts) -> SummaryInput:
        """버전에 맞는 LLM 입력 — 서비스·녹화 도구 공용(`prepare_summary_input`)."""
        return prepare_summary_input(self.prompt_version, facts, self.labels)

    def generate(
        self,
        facts_masked: dict[str, Any],
        fact_keys: list[str],
        examples: list[SummaryExample],
        *,
        deadline: float,
    ) -> SummaryGenerationResult:
        user = self._user(facts_masked, fact_keys, examples)
        self._preflight(deadline)
        totals = [0, 0, 0]  # tokens_in·tokens_out·latency_ms
        schema_errors = 0
        for attempt in range(SCHEMA_RETRY + 1):  # 1 + 1 = 2 호출
            res = self._llm.complete_json(
                system=self._system,
                user=user,
                model=self._s.llm_model_generate,
                max_tokens=SUMMARY_MAX_TOKENS,
                tag=self.prompt_version,
                timeout_s=self._s.summary_llm_timeout_s,  # 요약 전용 1회 제한(초안·검증은 llm_timeout_s)
            )
            totals = [totals[0] + res.tokens_in, totals[1] + res.tokens_out, totals[2] + res.latency_ms]
            try:
                parsed = SummaryOut.model_validate_json(res.text)
            except ValidationError as exc:
                schema_errors += 1
                log.warning(
                    "summary_schema_invalid", extra={"attempt": attempt + 1, "errors": len(exc.errors())}
                )
                if attempt >= SCHEMA_RETRY:
                    break
                self._preflight(deadline)
                continue
            return self._ok(parsed, res.model, totals, examples, self.prompt_version)
        # 예외 메시지에 LLM 응답 본문(ValidationError.input_value)이 들어가면 유출. 고정 문구만.
        raise LlmInvalidOutput(f"{self.prompt_version} schema invalid")

    def _user(
        self, facts_masked: dict[str, Any], fact_keys: list[str], examples: list[SummaryExample]
    ) -> str:
        return render_summary_user(
            self._user_tpl,
            facts_masked=facts_masked,
            fact_keys=fact_keys,
            examples=examples,
            labels=self.labels,
            prompt=self.prompt_version,
        )

    @staticmethod
    def _ok(
        parsed: SummaryOut, model: str, totals: list[int], examples: list[SummaryExample], prompt: str
    ) -> SummaryGenerationResult:
        return SummaryGenerationResult(
            summary_lines=list(parsed.summary_lines),
            model_focus=parsed.model_focus,
            llm_model=model,
            prompt_version=prompt,
            tokens_in=totals[0],
            tokens_out=totals[1],
            latency_ms=totals[2],
            few_shot_ids=[e.example_id for e in examples],
        )

    def _preflight(self, deadline: float) -> None:
        """남은 예산이 요약 호출 1회 제한보다 작으면 LlmUnavailable (SCRUM-129 커밋 전 수정).

        초안 `llm_timeout_s=35` 는 요약에 과도. 요약 전용 `summary_llm_timeout_s`(기본 15)로 체크 —
        "남은 시간 < 호출 1회 제한이면 안 부름" 불변식 유지. 재생성 판정은 서비스단 `_can_regenerate`.
        """
        remaining = deadline - self._clock()
        if remaining < self._s.summary_llm_timeout_s:
            raise LlmUnavailable("summary budget exceeded")


def merge_generations(
    first: SummaryGenerationResult, second: SummaryGenerationResult
) -> SummaryGenerationResult:
    """두 호출의 토큰·latency 합, 모델·내용은 2차 값 — 요약 재생성(★A 3) 합산."""
    return SummaryGenerationResult(
        summary_lines=second.summary_lines,
        model_focus=second.model_focus,
        llm_model=second.llm_model,
        prompt_version=second.prompt_version,
        tokens_in=first.tokens_in + second.tokens_in,
        tokens_out=first.tokens_out + second.tokens_out,
        latency_ms=first.latency_ms + second.latency_ms,
        few_shot_ids=second.few_shot_ids,
    )
