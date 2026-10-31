"""실제 LLM 1회 호출 → tests/str/recorded/{prompt_version}/{key}.json 저장.

사용: `uv run python -m tools.record --case fan_in`
- `.env` 의 LLM_API_KEY · LLM_MODEL_GENERATE 필요(AI_LLM_MOCK 은 무시 — 실제 호출)
- 입력: tests/str/fixtures/facts_<case>.json 의 Facts (이미 마스킹 된 모양)
- 저장 전: NarrativeOut 검증 + cites ⊆ fact_keys 확인, 실패하면 저장 안 함
- 저장 내용: {"text": "<LLM 응답 JSON 문자열>", "model": "<모델 ID>"} — API 키·헤더·토큰 수 안 들어감

녹화 파일 커밋 = 템플릿 동결 시점(docs/str/05). `FROZEN_PROMPTS` 에 파일 sha256 을 같은 커밋에 박는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient, recording_key
from aml_ai.shared.schemas.str import Facts, llm_output_model
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants import NARRATIVE_MAX_TOKENS
from aml_ai.str.domain.fact_keys import fact_keys
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.narrative_generator import load_prompt, render_user

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "str" / "fixtures"
RECORDED = REPO_ROOT / "tests" / "str" / "recorded"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    if settings.ai_llm_mock:
        print("ERROR: AI_LLM_MOCK=true 상태 — 실제 호출을 위해 false 로 설정하세요", file=sys.stderr)
        return 2
    facts_path = FIXTURES / f"facts_{args.case}.json"
    if not facts_path.exists():
        print(f"ERROR: fixture not found: {facts_path}", file=sys.stderr)
        return 2
    facts = Facts.model_validate(json.loads(facts_path.read_text(encoding="utf-8")))
    system, user, keys = _build_prompt(facts, settings.narrative_prompt)
    client = HttpLlmClient(settings)
    res = client.complete_json(
        system=system,
        user=user,
        model=settings.llm_model_generate,
        max_tokens=NARRATIVE_MAX_TOKENS,
        tag=settings.narrative_prompt,
    )
    err = _validate(res.text, keys, settings.narrative_prompt)
    if err:
        print(f"ERROR: {err} — 녹화 안 함", file=sys.stderr)
        return 3
    out_path = _save(recording_key(system, user), res.text, res.model, settings.narrative_prompt)
    print(
        f"✓ wrote {out_path.relative_to(REPO_ROOT)} "
        f"({len(res.text)} chars, model={res.model}, "
        f"latency_ms={res.latency_ms}, tokens_in={res.tokens_in}, tokens_out={res.tokens_out})"
    )
    return 0


def _build_prompt(facts: Facts, prompt_name: str) -> tuple[str, str, list[str]]:
    """draft_service._generate 와 동일한 user 프롬프트를 조립 — 녹화·재생 키 일치 (SCRUM-15 adversarial H3)."""
    system, user_tpl = load_prompt(prompt_name)
    examples = FewshotStore().pick_examples(facts.typology)
    keys = list(fact_keys(facts).keys())
    user = render_user(
        user_tpl,
        facts_masked=masking.mask_for_llm(facts),
        fact_keys=keys,
        notes=None,
        references=[],
        examples=examples,
    )
    return system, user, keys


def _validate(text: str, keys: list[str], prompt_name: str) -> str:
    """활성 버전 모델로 검증 — 응답 섹션 집합이 활성 버전과 다르면 거부(SCRUM-47)."""
    try:
        out = llm_output_model(prompt_name).model_validate_json(text)
    except ValidationError as exc:
        return f"{prompt_name} 출력 검증 실패: {exc}"
    scope = set(keys)
    for sec in out.narrative:
        bad = [c for c in sec.cites if c not in scope]
        if bad:
            return f"{sec.section.value} cites 가 FACT_KEYS 밖: {sorted(bad)[:5]}"
    return ""


def _save(key: str, text: str, model: str, prompt_name: str) -> Path:
    out_dir = RECORDED / prompt_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{key}.json"
    out_path.write_text(
        json.dumps({"text": text, "model": model}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out_path


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LLM 녹화 (docs/str/08)")
    p.add_argument("--case", required=True, help="tests/str/fixtures/facts_<case>.json")
    return p.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
