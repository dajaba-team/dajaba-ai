"""요약 녹화 (SCRUM-129) — summary_v1 프롬프트 + fewshot 2개 → recorded/summary_v1/<key>.json.

`tools/record.py` 가 `--summary` 모드에서 부른다. 관문(파일 200 줄) 때문에 분리.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient, recording_key
from aml_ai.shared.schemas.str import Facts, SummaryOut
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants import SUMMARY_MAX_TOKENS, SUMMARY_PROMPT
from aml_ai.str.domain.fact_keys import fact_keys
from aml_ai.str.infrastructure.narrative_generator import load_prompt
from aml_ai.str.infrastructure.summary_generator import load_summary_fewshot, render_summary_user


def record_summary(
    settings: Settings,
    facts: Facts,
    *,
    save: Callable[[str, str, str, str], Path],
    print_ok: Callable[[Path, object], None],
) -> int:
    system, user = _build_summary_prompt(facts)
    res = HttpLlmClient(settings).complete_json(
        system=system,
        user=user,
        model=settings.llm_model_generate,
        max_tokens=SUMMARY_MAX_TOKENS,
        tag=SUMMARY_PROMPT,
    )
    err = _validate_summary(res.text)
    if err:
        print(f"ERROR: {err} — 녹화 안 함", file=sys.stderr)
        return 3
    out_path = save(recording_key(system, user), res.text, res.model, SUMMARY_PROMPT)
    print_ok(out_path, res)
    return 0


def _build_summary_prompt(facts: Facts) -> tuple[str, str]:
    """summary_service._generate_and_check 와 같은 user — 녹화·재생 키 일치."""
    system, user_tpl = load_prompt(SUMMARY_PROMPT)
    examples = load_summary_fewshot(facts.typology)
    keys = list(fact_keys(facts).keys())
    user = render_summary_user(
        user_tpl, facts_masked=masking.mask_for_llm(facts), fact_keys=keys, examples=examples
    )
    return system, user


def _validate_summary(text: str) -> str:
    try:
        SummaryOut.model_validate_json(text)
    except ValidationError as exc:
        return f"{SUMMARY_PROMPT} 출력 검증 실패: {exc}"
    return ""
