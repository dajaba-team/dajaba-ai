"""프롬프트 조립 → LLM → NarrativeOut 검증 + cites ⊆ fact_keys 검사.

스키마 실패 또는 cites가 FACT_KEYS 밖이면 1회 재생성 → 또 실패면 LlmInvalidOutput (str/03 7단계, 05).
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
from aml_ai.shared.infrastructure.llm_client import LlmClient, LlmResult
from aml_ai.shared.schemas.str import NarrativeOut, Reference, llm_output_model
from aml_ai.str.domain.constants import NARRATIVE_MAX_TOKENS, SCHEMA_RETRY
from aml_ai.str.domain.models import Example, GenerationResult

log = logging.getLogger(__name__)
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> tuple[str, str]:
    """prompts/{name}.md → (system, user 템플릿). '[system]' / '[user]' 로 나눈다."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    body = text.split("```text", 1)[1].rsplit("```", 1)[0] if "```text" in text else text
    _, system_and_user = body.split("[system]", 1)
    system, user = system_and_user.split("[user]", 1)
    return system.strip(), user.strip()


def render_user(
    template: str,
    *,
    facts_masked: dict[str, Any],
    fact_keys: list[str],
    notes: str | None,
    references: list[Reference],
    examples: list[Example],
) -> str:
    refs = (
        "\n".join(f"[{i + 1}] {r.doc_title} p.{r.page}: {r.text or ''}" for i, r in enumerate(references))
        or "(없음)"
    )
    shots = "\n\n".join(
        f"FACTS:\n{json.dumps(e.facts.model_dump(mode='json'), ensure_ascii=False, indent=2)}\n"
        f"NARRATIVE:\n{json.dumps({'narrative': [s.model_dump() for s in e.narrative]}, ensure_ascii=False)}"
        for e in examples
    )
    return (
        template.replace("{{facts_json}}", json.dumps(facts_masked, ensure_ascii=False, indent=2))
        .replace("{{fact_keys}}", "\n".join(fact_keys) or "(없음)")
        .replace("{{investigator_notes}}", notes or "(없음)")
        .replace("{{references}}", refs)
        .replace("{{few_shot}}", shots)
    )


class NarrativeGenerator:
    def __init__(
        self,
        llm: LlmClient,
        settings: Settings,
        prompt_name: str = "narrative_v1",  # SCRUM-47 — draft_service.build 가 settings.narrative_prompt 전달
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._llm = llm
        self._s = settings
        self._clock = clock
        self.prompt_version = prompt_name
        self._system, self._user_tpl = load_prompt(prompt_name)

    def generate(
        self,
        facts_masked: dict[str, Any],
        fact_keys: list[str],
        examples: list[Example],
        references: list[Reference],
        notes: str | None,
        *,
        deadline: float,
    ) -> GenerationResult:
        self._preflight(deadline)
        user = render_user(
            self._user_tpl,
            facts_masked=facts_masked,
            fact_keys=fact_keys,
            notes=notes,
            references=references,
            examples=examples,
        )
        results: list[LlmResult] = []
        for attempt in range(1 + SCHEMA_RETRY):
            res = self._llm.complete_json(
                system=self._system,
                user=user,
                model=self._s.llm_model_generate,
                max_tokens=NARRATIVE_MAX_TOKENS,
                tag=self.prompt_version,
            )
            results.append(res)
            out = self._validate_result(res, fact_keys, attempt)
            if out is not None:
                return self._build_result(out, results, examples, references, notes)
            if attempt < SCHEMA_RETRY and not self._can_regenerate(deadline):
                break
        raise LlmInvalidOutput("narrative failed schema validation after retry")

    def _preflight(self, deadline: float) -> None:
        if deadline - self._clock() < self._s.llm_timeout_s:
            raise LlmUnavailable("draft budget exceeded")

    def _can_regenerate(self, deadline: float) -> bool:
        return deadline - self._clock() >= self._s.regen_min_remaining_s

    def _validate_result(self, res: LlmResult, fact_keys: list[str], attempt: int) -> NarrativeOut | None:
        """활성 버전 모델(NarrativeOutV1/V2) 로 검증 — 공용 NarrativeOut 로 두면 v2 모드가 v1 응답을 통과시킴.

        Codex adversarial 지적(SCRUM-47) 반영 — 모델 선택은 `llm_output_model(prompt_name)` 한 곳에서.
        """
        try:
            model = llm_output_model(self.prompt_version)
            out = model.model_validate_json(res.text)
            _check_cites_in_scope(out, fact_keys)
            return out
        except (ValidationError, ValueError) as exc:
            # 민감 입력 유출 방지(SCRUM-15 adversarial H2) — 유형·개수만 로그, str(exc) 는 쓰지 않음
            errors = getattr(exc, "error_count", lambda: 1)()
            log.warning(
                "narrative_schema_invalid",
                extra={"attempt": attempt + 1, "error_type": type(exc).__name__, "errors": errors},
            )
            return None

    def _build_result(
        self,
        out: NarrativeOut,
        results: list[LlmResult],
        examples: list[Example],
        references: list[Reference],
        notes: str | None,
    ) -> GenerationResult:
        return GenerationResult(
            narrative=out.narrative,
            llm_model=results[-1].model,
            prompt_version=self.prompt_version,
            tokens_in=sum(res.tokens_in for res in results),
            tokens_out=sum(res.tokens_out for res in results),
            latency_ms=sum(res.latency_ms for res in results),
            request_payload={
                "few_shot_ids": [e.example_id for e in examples],
                "reference_ids": [r.doc_id for r in references],
                "has_notes": bool(notes),
            },
            raw_response=results[-1].text,
        )


def _check_cites_in_scope(out: NarrativeOut, fact_keys: list[str]) -> None:
    """cites 는 모두 fact_keys 목록 안이어야 한다(str/03 7단계, 05 규칙 9).

    예외 메시지는 섹션 이름·개수만 — fact_keys 는 LLM 이 지어낸 문자열이라 입력값은 아니지만
    로그 금지 규칙에 맞춰 섹션만 노출.
    """
    scope = set(fact_keys)
    for sec in out.narrative:
        bad = sum(1 for c in sec.cites if c not in scope)
        if bad:
            raise ValueError(f"cites_out_of_scope section={sec.section.value} count={bad}")
