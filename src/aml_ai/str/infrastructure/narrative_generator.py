"""프롬프트 조립 → LLM → NarrativeOut 검증 + cites ⊆ fact_keys 검사.

스키마 실패 또는 cites가 FACT_KEYS 밖이면 1회 재생성 → 또 실패면 LlmInvalidOutput (str/03 7단계, 05).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.llm_client import LlmClient
from aml_ai.shared.schemas.str import NarrativeOut, Reference
from aml_ai.str.domain.constants import NARRATIVE_MAX_TOKENS, NARRATIVE_PROMPT, SCHEMA_RETRY
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
    def __init__(self, llm: LlmClient, settings: Settings, prompt_name: str = NARRATIVE_PROMPT) -> None:
        self._llm = llm
        self._s = settings
        self.prompt_version = prompt_name
        self._system, self._user_tpl = load_prompt(prompt_name)

    def generate(
        self,
        facts_masked: dict[str, Any],
        fact_keys: list[str],
        examples: list[Example],
        references: list[Reference],
        notes: str | None,
    ) -> GenerationResult:
        user = render_user(
            self._user_tpl,
            facts_masked=facts_masked,
            fact_keys=fact_keys,
            notes=notes,
            references=references,
            examples=examples,
        )
        for attempt in range(1 + SCHEMA_RETRY):
            res = self._llm.complete_json(
                system=self._system,
                user=user,
                model=self._s.llm_model_generate,
                max_tokens=NARRATIVE_MAX_TOKENS,
                tag=self.prompt_version,
            )
            try:
                out = NarrativeOut.model_validate_json(res.text)
                _check_cites_in_scope(out, fact_keys)
            except (ValidationError, ValueError) as exc:
                # 민감 입력 유출 방지(SCRUM-15 adversarial H2) — 유형·개수만 로그, str(exc) 는 쓰지 않음
                errors = getattr(exc, "error_count", lambda: 1)()
                log.warning(
                    "narrative_schema_invalid",
                    extra={"attempt": attempt + 1, "error_type": type(exc).__name__, "errors": errors},
                )
                continue
            return self._build_result(out, res, examples, references, notes)
        raise LlmInvalidOutput("narrative failed schema validation after retry")

    def _build_result(
        self,
        out: NarrativeOut,
        res,
        examples: list[Example],
        references: list[Reference],
        notes: str | None,
    ) -> GenerationResult:
        return GenerationResult(
            narrative=out.narrative,
            llm_model=res.model,
            prompt_version=self.prompt_version,
            tokens_in=res.tokens_in,
            tokens_out=res.tokens_out,
            latency_ms=res.latency_ms,
            request_payload={
                "few_shot_ids": [e.example_id for e in examples],
                "reference_ids": [r.doc_id for r in references],
                "has_notes": bool(notes),
            },
            raw_response=res.text,
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
