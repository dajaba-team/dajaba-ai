"""평가자 LLM — 코드 검증 통과 뒤에만. comment 먼저, score 나중 (docs/str/06, 05)."""

from __future__ import annotations

import json

from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.llm_client import LlmClient
from aml_ai.shared.schemas.str import Facts, JudgeOut, LlmCheck, NarrativeSection
from aml_ai.str.domain.constants import JUDGE_MAX_TOKENS, JUDGE_PROMPT
from aml_ai.str.infrastructure.narrative_generator import load_prompt


class Judge:
    def __init__(self, llm: LlmClient, settings: Settings, prompt_name: str = JUDGE_PROMPT) -> None:
        self._llm = llm
        self._s = settings
        self.prompt_version = prompt_name
        self._system, self._user_tpl = load_prompt(prompt_name)

    def run(self, facts: Facts, narrative: list[NarrativeSection]) -> list[LlmCheck]:
        user = self._user_tpl.replace(
            "{{facts_json}}", json.dumps(facts.model_dump(mode="json"), ensure_ascii=False, indent=2)
        ).replace(
            "{{narrative_json}}",
            json.dumps({"narrative": [s.model_dump() for s in narrative]}, ensure_ascii=False, indent=2),
        )
        model = self._s.llm_model_judge or self._s.llm_model_generate
        res = self._llm.complete_json(
            system=self._system, user=user, model=model, max_tokens=JUDGE_MAX_TOKENS, tag=self.prompt_version
        )
        try:
            return JudgeOut.model_validate_json(res.text).checks
        except (ValidationError, ValueError) as exc:
            raise LlmInvalidOutput("judge output failed schema", detail=str(exc)[:300]) from exc
