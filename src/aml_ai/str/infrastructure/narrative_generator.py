"""프롬프트 조립 → LLM → NarrativeOut 스키마 검증. 스키마 실패 1회 재생성 → 또 실패면 LlmInvalidOutput (docs/str/05)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.llm_client import LlmClient
from aml_ai.shared.schemas.str import Facts, NarrativeOut, Reference
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
    facts_masked: Facts,
    transaction_ids: list[int],
    notes: str | None,
    references: list[Reference],
    examples: list[Example],
) -> str:
    refs = (
        "\n".join(f"[{i + 1}] {r.doc_title} p.{r.page}: {r.text or ''}" for i, r in enumerate(references))
        or "(없음)"
    )
    shots = "\n\n".join(
        f"FACTS:\n{json.dumps(e.facts.model_dump(mode='json'), ensure_ascii=False, indent=2)}\nNARRATIVE:\n{json.dumps({'narrative': [s.model_dump() for s in e.narrative]}, ensure_ascii=False)}"
        for e in examples
    )
    return (
        template.replace(
            "{{facts_json}}", json.dumps(facts_masked.model_dump(mode="json"), ensure_ascii=False, indent=2)
        )
        .replace("{{transaction_ids}}", ", ".join(map(str, transaction_ids)))
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
        facts_masked: Facts,
        examples: list[Example],
        references: list[Reference],
        notes: str | None,
        transaction_ids: list[int] | None = None,
    ) -> GenerationResult:
        user = render_user(
            self._user_tpl,
            facts_masked=facts_masked,
            transaction_ids=transaction_ids or [],
            notes=notes,
            references=references,
            examples=examples,
        )
        last_error = ""
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
            except (ValidationError, ValueError) as exc:
                last_error = str(exc)[:300]
                log.warning("narrative_schema_invalid", extra={"attempt": attempt + 1})
                continue
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
        raise LlmInvalidOutput("narrative failed schema validation after retry", detail=last_error)
