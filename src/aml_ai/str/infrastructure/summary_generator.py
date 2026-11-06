"""summary_v1 생성기 — 프롬프트 조립 → LLM → SummaryOut 검증. 재생성 1회 (SCRUM-129).

스키마 실패면 남은 예산 안에서 1회 재생성. 두 번 다 실패면 `LlmInvalidOutput`. 코드 검사 실패는
호출 측(`summary_service`)이 다시 호출해 재생성한다 — 이 모듈은 "스키마" 재생성만 관리.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.infrastructure.llm_client import LlmClient
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts, SummaryOut
from aml_ai.str.domain.constants import SCHEMA_RETRY, SUMMARY_MAX_TOKENS, SUMMARY_PROMPT
from aml_ai.str.domain.models import SummaryExample, SummaryGenerationResult
from aml_ai.str.infrastructure.narrative_generator import load_prompt

log = logging.getLogger(__name__)
FEWSHOT_ROOT = Path(__file__).resolve().parent.parent / "fewshot"
SUMMARY_FEWSHOT_COUNT = 2  # fewshot/summary_v1/001·002 (같은 유형 1 + 다른 유형 1)


def render_summary_user(
    template: str,
    *,
    facts_masked: dict[str, Any],
    fact_keys: list[str],
    examples: list[SummaryExample],
) -> str:
    """draft 와 같은 자리 치환 — few-shot 은 요약 모양."""
    shots = "\n\n".join(
        f"FACTS:\n{json.dumps(e.facts.model_dump(mode='json'), ensure_ascii=False, indent=2)}\n"
        f"SUMMARY:\n{json.dumps({'summary_lines': e.summary_lines, 'model_focus': e.model_focus}, ensure_ascii=False)}"
        for e in examples
    )
    return (
        template.replace("{{facts_json}}", json.dumps(facts_masked, ensure_ascii=False, indent=2))
        .replace("{{fact_keys}}", "\n".join(fact_keys) or "(없음)")
        .replace("{{few_shot}}", shots)
    )


def load_summary_fewshot(typology: Typology | None, *, directory: Path | None = None) -> list[SummaryExample]:
    """fewshot/summary_v1/*.json — 같은 유형 1 + 다른 유형 1 (총 2)."""
    directory = directory or (FEWSHOT_ROOT / SUMMARY_PROMPT)
    all_examples: list[SummaryExample] = sorted(
        (_load_example(p) for p in directory.glob("*.json")), key=lambda e: e.example_id
    )
    same = [e for e in all_examples if e.typology == typology][:1]
    other = [e for e in all_examples if e.typology != typology][:1]
    picked = (same + other)[:SUMMARY_FEWSHOT_COUNT]
    return picked


def _load_example(path: Path) -> SummaryExample:
    d = json.loads(path.read_text(encoding="utf-8"))
    return SummaryExample(
        example_id=int(d["example_id"]),
        typology=d["typology"],
        facts=Facts.model_validate(d["facts"]),
        summary_lines=list(d["summary_lines"]),
        model_focus=d.get("model_focus"),
    )


class SummaryGenerator:
    """프롬프트·LLM 호출·스키마 검증·재생성 1회 (SCRUM-129)."""

    def __init__(
        self,
        llm: LlmClient,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._llm = llm
        self._s = settings
        self._clock = clock
        self.prompt_version = SUMMARY_PROMPT
        self._system, self._user_tpl = load_prompt(SUMMARY_PROMPT)

    def generate(
        self,
        facts_masked: dict[str, Any],
        fact_keys: list[str],
        examples: list[SummaryExample],
        *,
        deadline: float,
    ) -> SummaryGenerationResult:
        user = render_summary_user(
            self._user_tpl, facts_masked=facts_masked, fact_keys=fact_keys, examples=examples
        )
        self._preflight(deadline)
        totals = [0, 0, 0]  # tokens_in·tokens_out·latency_ms
        schema_errors = 0
        for attempt in range(SCHEMA_RETRY + 1):  # 1 + 1 = 2 호출
            res = self._llm.complete_json(
                system=self._system,
                user=user,
                model=self._s.llm_model_generate,
                max_tokens=SUMMARY_MAX_TOKENS,
                tag=SUMMARY_PROMPT,
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
            return self._ok(parsed, res.model, totals, examples)
        # 예외 메시지에 LLM 응답 본문(ValidationError.input_value)이 들어가면 유출. 고정 문구만.
        raise LlmInvalidOutput("summary_v1 schema invalid")

    @staticmethod
    def _ok(
        parsed: SummaryOut, model: str, totals: list[int], examples: list[SummaryExample]
    ) -> SummaryGenerationResult:
        return SummaryGenerationResult(
            summary_lines=list(parsed.summary_lines),
            model_focus=parsed.model_focus,
            llm_model=model,
            prompt_version=SUMMARY_PROMPT,
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
