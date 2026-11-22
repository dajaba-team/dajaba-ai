"""요약 녹화 (SCRUM-129) — `SUMMARY_PROMPT`(지금 summary_v2) 프롬프트 + fewshot 2개 → recorded/<SUMMARY_PROMPT>/<key>.json.

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
from aml_ai.str.domain.constants import SUMMARY_MAX_TOKENS, SUMMARY_PROMPT
from aml_ai.str.infrastructure.narrative_generator import load_prompt
from aml_ai.str.infrastructure.summary_prompt_input import (
    labels_for,
    prepare_summary_input,
    render_summary_user,
)


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


def _build_summary_prompt(facts: Facts, prompt: str = SUMMARY_PROMPT) -> tuple[str, str]:
    """summary_service 와 같은 user — 같은 버전별 입력 함수(`prepare_summary_input`)라 녹화·재생 키 일치."""
    system, user_tpl = load_prompt(prompt)
    labels = labels_for(prompt)  # v2 일 때만 사전(검토 2 M6)
    inp = prepare_summary_input(prompt, facts, labels)
    user = render_summary_user(user_tpl, facts_masked=inp.facts_llm, fact_keys=inp.fact_keys, examples=inp.examples, labels=labels, prompt=prompt)  # fmt: skip
    return system, user


def _validate_summary(text: str) -> str:
    try:
        SummaryOut.model_validate_json(text)
    except ValidationError as exc:
        return f"{SUMMARY_PROMPT} 출력 검증 실패: {exc}"
    return ""
