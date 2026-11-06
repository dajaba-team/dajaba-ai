"""실제 LLM 1회 호출 → tests/str/recorded/{prompt_version}/{key}.json 저장.

생성(narrative): `uv run python -m tools.record --case fan_in`
평가자(judge, SCRUM-61): `uv run python -m tools.record --judge --case fan_in --from-recorded narrative_v1/<key>.json`
요약(summary, SCRUM-129): `uv run python -m tools.record --summary --case fan_in`
- `.env` 의 LLM_API_KEY · LLM_MODEL_GENERATE·LLM_MODEL_JUDGE 필요(AI_LLM_MOCK 은 무시 — 실제 호출)
- 저장 전: 해당 출력 스키마 검증(요약은 1~6줄·한 줄 ≤80자·숫자 신호 이름 통과 정책 그대로).
- 저장 내용: {"text": "<LLM 응답 JSON 문자열>", "model": "<모델 ID>"} — API 키·헤더·토큰 수 안 들어감

녹화 파일 커밋 = 템플릿 동결 시점(docs/str/05). `FROZEN_PROMPTS` 에 파일 sha256 을 같은 커밋에 박는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient, recording_key
from aml_ai.shared.schemas.str import Facts, NarrativeOut, llm_output_model
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants import JUDGE_MAX_TOKENS, JUDGE_PROMPT, NARRATIVE_MAX_TOKENS
from aml_ai.str.domain.fact_keys import attach_evidence, fact_keys
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.judge import judge_model_decision, render_judge_user
from aml_ai.str.infrastructure.narrative_generator import load_prompt, render_user

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "str" / "fixtures"
RECORDED = REPO_ROOT / "tests" / "str" / "recorded"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    if settings.ai_llm_mock:
        print("ERROR: AI_LLM_MOCK=true — 실제 호출을 위해 false 로 설정", file=sys.stderr)
        return 2
    facts = _load_facts(args.case)
    if facts is None:
        return 2
    if args.judge:
        return _record_judge(settings, facts, args.from_recorded)
    if args.summary:
        from tools.record_summary import record_summary

        return record_summary(settings, facts, save=_save, print_ok=_print_ok)
    return _record_narrative(settings, facts)


def _load_facts(case: str) -> Facts | None:
    facts_path = FIXTURES / f"facts_{case}.json"
    if not facts_path.exists():
        print(f"ERROR: fixture not found: {facts_path}", file=sys.stderr)
        return None
    return Facts.model_validate(json.loads(facts_path.read_text(encoding="utf-8")))


def _record_narrative(settings: Settings, facts: Facts) -> int:
    system, user, keys = _build_prompt(facts, settings.narrative_prompt)
    res = HttpLlmClient(settings).complete_json(
        system=system,
        user=user,
        model=settings.llm_model_generate,
        max_tokens=NARRATIVE_MAX_TOKENS,
        tag=settings.narrative_prompt,
    )
    err = _validate_narrative(res.text, keys, settings.narrative_prompt)
    if err:
        print(f"ERROR: {err} — 녹화 안 함", file=sys.stderr)
        return 3
    out_path = _save(recording_key(system, user), res.text, res.model, settings.narrative_prompt)
    _print_ok(out_path, res)
    return 0


def _record_judge(settings: Settings, facts: Facts, from_recorded: str | None) -> int:
    if not from_recorded:
        print("ERROR: --judge 는 --from-recorded <narrative_vX/<key>.json> 필요", file=sys.stderr)
        return 2
    narrative_path = RECORDED / from_recorded
    if not narrative_path.exists():
        print(f"ERROR: recorded narrative not found: {narrative_path}", file=sys.stderr)
        return 2
    narrative = _load_narrative(narrative_path, facts)
    keys = list(fact_keys(facts).keys())
    request_sections = [s.section.value for s in narrative]
    system, user_tpl = load_prompt(JUDGE_PROMPT)
    user = render_judge_user(
        user_tpl,
        facts_masked=masking.mask_for_llm(facts),
        narrative=narrative,
        fact_keys=keys,
        request_sections=request_sections,
    )
    model, _reason = judge_model_decision(settings)
    res = HttpLlmClient(settings).complete_json(
        system=system, user=user, model=model, max_tokens=JUDGE_MAX_TOKENS, tag=JUDGE_PROMPT
    )
    err = _validate_judge(res.text, request_sections, keys)
    if err:
        print(f"ERROR: {err} — 녹화 안 함", file=sys.stderr)
        return 3
    out_path = _save(recording_key(system, user), res.text, res.model, JUDGE_PROMPT)
    _print_ok(out_path, res)
    return 0


def _load_narrative(path: Path, facts: Facts) -> list:
    """생성 녹화에서 본문 복원 — attach_evidence 로 evidence_ids 까지 채운 NarrativeSection 리스트."""
    recorded = json.loads(path.read_text(encoding="utf-8"))
    out = NarrativeOut.model_validate_json(recorded["text"])
    return attach_evidence(out.narrative, facts)


def _build_prompt(facts: Facts, prompt_name: str) -> tuple[str, str, list[str]]:
    """draft_service._generate 와 동일한 user — 녹화·재생 키 일치(SCRUM-15 adversarial H3)."""
    system, user_tpl = load_prompt(prompt_name)
    examples = FewshotStore(prompt_name=prompt_name).pick_examples(facts.typology)
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


def _validate_narrative(text: str, keys: list[str], prompt_name: str) -> str:
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


def _validate_judge(text: str, request_sections: list[str], keys: list[str]) -> str:
    """judge_v2 출력 — 스키마 + sections 집합 일치 + cites 는 FACT_KEYS 밖이면 경고(저장은 함)."""
    try:
        out = llm_output_model(JUDGE_PROMPT).model_validate_json(text)
    except ValidationError as exc:
        return f"{JUDGE_PROMPT} 출력 검증 실패: {exc}"
    if {s.section.value for s in out.sections} != set(request_sections):
        return f"{JUDGE_PROMPT} sections 집합이 요청과 다름"
    scope = set(keys)
    for sec in out.sections:
        bad = [c for c in sec.cites if c not in scope]
        if bad:
            print(f"WARN: {sec.section.value} cites 밖 키 {sorted(bad)[:5]} — 저장은 하되 verify 가 버림")
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


def _print_ok(out_path: Path, res) -> None:
    print(
        f"✓ wrote {out_path.relative_to(REPO_ROOT)} "
        f"({len(res.text)} chars, model={res.model}, "
        f"latency_ms={res.latency_ms}, tokens_in={res.tokens_in}, tokens_out={res.tokens_out})"
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LLM 녹화 (docs/str/08)")
    p.add_argument("--case", required=True, help="tests/str/fixtures/facts_<case>.json")
    p.add_argument("--judge", action="store_true", help="평가자 녹화 (SCRUM-61)")
    p.add_argument("--summary", action="store_true", help="요약 녹화 (SCRUM-129)")
    p.add_argument("--from-recorded", help="평가자 녹화 입력 — tests/str/recorded/<prompt>/<key>.json")
    return p.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
