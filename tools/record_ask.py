"""ask_plan_v1 녹화 — 평가 세트 18개 질문 → tests/str/recorded/ask_plan_v1/<key>.json + 분류 표 (SCRUM-290, docs/str/08).

    AI_LLM_MOCK=false uv run --frozen --extra dev python -m tools.record_ask --plan

계획은 facts 를 안 받으므로 질문(계좌 가린 것)만으로 녹화 키가 정해진다 — 서비스(`AskLlm.plan`)와 같은 조립 함수.
스키마를 못 지난 응답은 저장하지 않는다. 저장 내용 {"text", "model"} 만(키·헤더·토큰 수 없음).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

from pydantic import ValidationError

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.errors import AiError
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient, recording_key
from aml_ai.shared.schemas.str.ask_llm import AskPlanOut
from aml_ai.shared.versioning import file_sha256
from aml_ai.str.domain.ask_question import mask_question
from aml_ai.str.domain.constants_ask import ASK_PLAN_MAX_TOKENS, ASK_PLAN_PROMPT
from aml_ai.str.infrastructure.ask_llm import render_plan_user
from aml_ai.str.infrastructure.narrative_generator import PROMPTS_DIR, load_prompt
from tools.record import FIXTURES, _save

EVAL_SET = FIXTURES / "ask_eval_set.json"


@dataclass
class Row:
    item: dict
    got: str  # "FACT [flows]" · "OUT_OF_SCOPE JUDGMENT" · "ERROR <code>"
    ok: bool
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="질문 답변 녹화 (docs/str/08)")
    p.add_argument("--plan", action="store_true", required=True, help="ask_plan_v1 18개")
    p.add_argument("--only", help="쉼표로 id 만 (예 O4,F7)")
    args = p.parse_args(argv)
    settings = get_settings()
    if settings.ai_llm_mock:
        print("ERROR: AI_LLM_MOCK=true — 실제 호출을 위해 false 로 설정", file=sys.stderr)
        return 2
    items = json.loads(EVAL_SET.read_text(encoding="utf-8"))["items"]
    if args.only:
        wanted = set(args.only.split(","))
        items = [i for i in items if i["id"] in wanted]
    rows = [_record_one(settings, item) for item in items]
    _print_table(rows)
    print(f'FROZEN_PROMPTS["{ASK_PLAN_PROMPT}"] = "{file_sha256(PROMPTS_DIR / f"{ASK_PLAN_PROMPT}.md")}"')
    return 0 if all(not r.got.startswith("ERROR") for r in rows) else 3


def _record_one(settings: Settings, item: dict) -> Row:
    system, tpl = load_prompt(ASK_PLAN_PROMPT)
    user = render_plan_user(tpl, mask_question(item["question"]))
    try:
        res = HttpLlmClient(settings).complete_json(
            system=system,
            user=user,
            model=settings.llm_model_generate,
            max_tokens=ASK_PLAN_MAX_TOKENS,
            tag=ASK_PLAN_PROMPT,
            timeout_s=settings.ask_llm_timeout_s,
            total_timeout_s=settings.ask_llm_timeout_s,  # 서비스와 같은 호출 전체 제한
        )
    except AiError as exc:
        return Row(item, f"ERROR {exc.code}", ok=False)
    try:
        out = AskPlanOut.model_validate_json(res.text)
    except ValidationError:
        return Row(item, "ERROR schema", ok=False, latency_ms=res.latency_ms)
    _save(recording_key(system, user), res.text, res.model, ASK_PLAN_PROMPT)
    return Row(item, _describe(out), _matches(item, out), res.latency_ms, res.tokens_in, res.tokens_out)


def _describe(out: AskPlanOut) -> str:
    if out.out_of_scope_reason is not None:
        return f"{out.kind.value} {out.out_of_scope_reason.value}"
    return f"{out.kind.value} [{','.join(b.value for b in out.bundles)}]"


def _matches(item: dict, out: AskPlanOut) -> bool:
    """08 계획 분류 — kind 같음 + (사유 무관이 아니면) 사유 같음 + 기대 묶음 포함."""
    if out.kind.value != item["expected_kind"]:
        return False
    reason = out.out_of_scope_reason.value if out.out_of_scope_reason else None
    if item["expected_reason"] is not None and reason != item["expected_reason"]:
        return False
    bundle = item["expected_bundle"]
    return bundle is None or bundle in {b.value for b in out.bundles}


def _print_table(rows: list[Row]) -> None:
    print("| # | 기대 | 결과 | 맞음 | latency_ms | tokens_in | tokens_out |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        i = r.item
        want = f"{i['expected_kind']} {i['expected_reason'] or ''} {i['expected_bundle'] or ''}".strip()
        mark = "O" if r.ok else "X"
        print(f"| {i['id']} | {want} | {r.got} | {mark} | {r.latency_ms} | {r.tokens_in} | {r.tokens_out} |")
    oos = [r for r in rows if r.item["expected_kind"] == "OUT_OF_SCOPE"]
    oos_ok = sum(r.got.startswith("OUT_OF_SCOPE") for r in oos)
    done = [r for r in rows if not r.got.startswith("ERROR")]
    n = max(len(done), 1)
    print(f"범위 밖 OUT_OF_SCOPE {oos_ok}/{len(oos)} · 분류 틀림 {sum(not r.ok for r in rows)}/{len(rows)}")
    print(
        f"계획 latency 최대 {max((r.latency_ms for r in done), default=0)}ms · "
        f"평균 tokens_in {sum(r.tokens_in for r in done) // n} · tokens_out {sum(r.tokens_out for r in done) // n}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
