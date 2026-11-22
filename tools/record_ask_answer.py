"""ask_answer_v1 녹화 — 평가 세트 범위 안 12개 → tests/str/recorded/ask_answer_v1/<key>.json + 평가 표 (SCRUM-290 2/2, 08).

    AI_LLM_MOCK=false uv run --frozen --extra dev python -m tools.record_ask_answer

항목마다 실제 계획 + 실제 답을 서비스와 같은 함수(`AskLlm`·`extract`·`in_scope_response`)로 불러 합 지연을 잰다.
facts 는 평가 세트의 픽스처(서비스 수준 주입). 실제 계획 묶음이 `recorded/ask_plan_v1/` 녹화본과 다르면 답을 저장하지
않는다(재생 때 키가 안 맞음). 계획 녹화는 덮어쓰지 않는다. 저장 내용 {"text", "model"} 만. 답 본문은 찍지 않는다.

`--premise` (SCRUM-358) — 전제·방향 평가 세트 11개. 계획 녹화가 없으면 이번 실제 계획을 새로 저장하고(있으면 위처럼
비교), 판정(`tools/ask_premise_judge.py`) 칸과 목표 줄을 더 찍는다. 판정 낱말만 — 답 본문은 여기서도 안 찍는다.

    AI_LLM_MOCK=false uv run --frozen --extra dev python -m tools.record_ask_answer --premise

`--set gaps` (SCRUM-359) — 사각지대 측정 세트 16개, `--premise` 와 같은 방식(`--premise` = `--set premise`).

    AI_LLM_MOCK=false uv run --frozen --extra dev python -m tools.record_ask_answer --set gaps
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.errors import AiError
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient, LlmResult, RecordedLlmClient, recording_key
from aml_ai.shared.schemas.str import AskRequest, Facts
from aml_ai.shared.schemas.str.ask_llm import AskPlanKind
from aml_ai.shared.versioning import file_sha256
from aml_ai.str.application.ask_answer import in_scope_response
from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.domain.ask_question import mask_question
from aml_ai.str.domain.constants_ask import ASK_ANSWER_PROMPT, ASK_PLAN_PROMPT
from aml_ai.str.infrastructure.ask_llm import AskLlm
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.narrative_generator import PROMPTS_DIR
from tools import ask_premise_judge as judge
from tools.record import FIXTURES, RECORDED, _save
from tools.record_ask import EVAL_SET

EXAMPLES = FIXTURES.parents[2] / "contracts" / "examples"


@dataclass
class Capture:
    """실제 클라이언트를 감싸 마지막 호출의 인자·결과를 남긴다(저장용)."""

    inner: HttpLlmClient
    calls: list[tuple[dict, LlmResult]] = field(default_factory=list)

    def complete_json(self, **kw) -> LlmResult:
        res = self.inner.complete_json(**kw)
        self.calls.append((kw, res))
        return res


@dataclass
class Row:
    id: str
    status: str  # ANSWERED · NO_DATA · UNVERIFIED · 계획 다름 · ERROR <code>
    failed: str = ""
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    mark: str = ""  # --premise·--set 판정


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="질문 답변 답 녹화 (docs/str/08)")
    p.add_argument("--only", help="쉼표로 id 만 (예 F1,W3)")
    p.add_argument(
        "--premise", action="store_true", help="전제·방향 평가 세트 11개(SCRUM-358) = --set premise"
    )
    p.add_argument("--set", choices=sorted(judge.SETS), help="판정 세트(premise 11 · gaps 16)")
    args = p.parse_args(argv)
    settings = get_settings()
    if settings.ai_llm_mock:
        print("ERROR: AI_LLM_MOCK=true — 실제 호출을 위해 false 로 설정", file=sys.stderr)
        return 2
    name = "premise" if args.premise else args.set
    source, targets = judge.SETS[name] if name else (EVAL_SET, None)
    items = [
        i
        for i in json.loads(source.read_text(encoding="utf-8"))["items"]
        if i["expected_kind"] != "OUT_OF_SCOPE"
    ]
    if args.only:
        items = [i for i in items if i["id"] in set(args.only.split(","))]
    rows = [_record_one(settings, item, new_plan=targets is not None) for item in items]
    _print_table(rows)
    if targets is not None:
        marks = [judge.Row(i, r.mark, r.latency_ms, r.status) for i, r in zip(items, rows, strict=True)]
        print(" · ".join(targets(marks)))
    print(f'FROZEN_PROMPTS["{ASK_ANSWER_PROMPT}"] = "{file_sha256(PROMPTS_DIR / f"{ASK_ANSWER_PROMPT}.md")}"')
    done = {"ANSWERED", "NO_DATA", "UNVERIFIED"} | ({"OUT_OF_SCOPE"} if targets is not None else set())
    return 0 if all(r.status in done for r in rows) else 3


def _request(item: dict) -> AskRequest:
    body = json.loads((EXAMPLES / "ask_request.json").read_text(encoding="utf-8"))
    body["alert"] = {**body["alert"], "rule_id": item["rule_id"]}
    return AskRequest.model_validate({**body, "question": item["question"]})


def _record_one(settings: Settings, item: dict, *, new_plan: bool = False) -> Row:
    facts = Facts.model_validate_json(
        (FIXTURES / f"facts_{item['facts_case']}.json").read_text(encoding="utf-8")
    )
    req, question = _request(item), mask_question(item["question"])
    real = Capture(HttpLlmClient(settings))
    llm = AskLlm(real, settings)
    start = time.monotonic()
    deadline = start + settings.ask_budget_s  # 서비스와 같은 예산
    try:
        plan = llm.plan(question, deadline=deadline)
        if not (new_plan and _save_plan_if_new(real.calls[-1])):
            saved_plan = AskLlm(RecordedLlmClient(RECORDED), settings).plan(question, deadline=float("inf"))
            if _plan_sig(plan.out) != _plan_sig(saved_plan.out):
                return Row(item["id"], "계획 다름", latency_ms=_ms(start))
        if plan.out.kind is AskPlanKind.OUT_OF_SCOPE:  # 서비스처럼 답 호출 없음(SCRUM-359)
            return Row(
                item["id"], "OUT_OF_SCOPE", "", _ms(start), plan.tokens_in, plan.tokens_out, judge.OTHER
            )
        piece = extract(facts, req.alert.rule_id, [b.value for b in plan.out.bundles], load_display_labels())
        ans = llm.answer(question, piece, deadline=deadline)
    except AiError as exc:
        return Row(item["id"], f"ERROR {exc.code}", latency_ms=_ms(start))
    elapsed = _ms(start)
    kw, res = real.calls[-1]
    _save(recording_key(kw["system"], kw["user"]), res.text, res.model, ASK_ANSWER_PROMPT)
    out = in_scope_response(req, "g-record", facts, plan, piece, ans, settings.server_version)
    failed = ",".join(c.check.value for c in out.code_checks if not c.match)
    mark = judge.verdict(item, out.status.value, ans.out.answer) if new_plan else ""
    return Row(
        item["id"],
        out.status.value,
        failed,
        elapsed,
        plan.tokens_in + ans.tokens_in,
        plan.tokens_out + ans.tokens_out,
        mark,
    )


def _save_plan_if_new(call: tuple[dict, LlmResult]) -> bool:
    """계획 녹화가 없을 때만 저장(덮어쓰기 0). 저장했으면 True — 비교할 녹화가 이번 것."""
    kw, res = call
    key = recording_key(kw["system"], kw["user"])
    if (RECORDED / ASK_PLAN_PROMPT / f"{key}.json").exists():
        return False
    _save(key, res.text, res.model, ASK_PLAN_PROMPT)
    return True


def _plan_sig(out) -> tuple:
    """조각은 묶음 순서와 무관(키 순서는 fact_keys, 내용은 키 정렬 JSON) — 집합으로 비교."""
    return out.kind, out.out_of_scope_reason, frozenset(out.bundles)


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _print_table(rows: list[Row]) -> None:
    print("| # | 상태 | 검사 실패 | 계획+답 ms | tokens_in | tokens_out | 판정 |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r.id} | {r.status} | {r.failed or '-'} | {r.latency_ms} | {r.tokens_in} | {r.tokens_out} "
            f"| {r.mark or '-'} |"
        )
    facts_ok = sum(r.id.startswith("F") and r.status == "ANSWERED" for r in rows)
    n_facts = sum(r.id.startswith("F") for r in rows)
    unverified = sum(r.status == "UNVERIFIED" for r in rows)
    done = [r for r in rows if r.tokens_in]
    n = max(len(done), 1)
    print(f"사실 ANSWERED {facts_ok}/{n_facts} · UNVERIFIED {unverified}/{len(rows)}")
    print(
        f"계획+답 최대 {max((r.latency_ms for r in rows), default=0)}ms · "
        f"평균 tokens_in {sum(r.tokens_in for r in done) // n} · tokens_out {sum(r.tokens_out for r in done) // n}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
