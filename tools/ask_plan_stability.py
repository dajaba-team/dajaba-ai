"""질문 답변 계획 흔들림 재기 — 48문항 × N회 계획만 호출, 계획 녹화와 비교 (SCRUM-362 ★B4, docs/str/08).

    AI_LLM_MOCK=false uv run --frozen --extra dev python -m tools.ask_plan_stability --n 5

대상 = 18개 평가 세트 18(범위 안 12 + 범위 밖 6) · 358 세트 11 · 359 세트 15(C2 는 코드 차단이라 계획 호출 없음)
· 복합 WHY 4(`362:K1~K4`, 추가 검토 1 — ask_plan_v3 부터) = 48.
비교 기준 = `recorded/<계획 프롬프트>/` 녹화 계획(재생에 쓰는 것). "다름" = 녹화 도구 `_plan_sig` 와 같음 —
kind · out_of_scope_reason · **코드가 실제로 꺼낸 묶음(`with_flows` 뒤) 집합** 중 하나라도 다르면 다름(SCRUM-362 ★B4-2 —
고치기 전 재기 결과를 본 뒤 바꾼 정의: 답 입력이 같으면 같음). 묶음 순서만 다른 것은 같음. 스키마 위반·오류는 실패.
목표(결과 보기 전 고정): 대상 모두 N/N 같음 · 실패 0. 고친 뒤엔 더해서 **기대 계획과 같음 전부**
(`tests/str/fixtures/ask_plan_expected.json` — v2 로 바꾸기 전 고정, 같은 정의). **녹화 파일은 읽기만 한다**(저장 안 함).
출력은 문항 id·같음 수·다른 칸(묶음 이름)·지연·토큰만 — 질문·답 본문 없음.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.errors import AiError
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient, LlmClient, RecordedLlmClient
from aml_ai.shared.schemas.str.ask import OutOfScopeReason
from aml_ai.shared.schemas.str.ask_llm import AskPlanKind, AskPlanOut
from aml_ai.shared.versioning import file_sha256
from aml_ai.str.domain.ask_question import blocked_before_plan, mask_question
from aml_ai.str.domain.constants_ask import ASK_PLAN_PROMPT
from aml_ai.str.infrastructure.ask_llm import AskLlm
from aml_ai.str.infrastructure.narrative_generator import PROMPTS_DIR
from tools import ask_premise_judge as judge
from tools.ask_plan_sig import _plan_sig, plan_bundles
from tools.record import FIXTURES, RECORDED
from tools.record_ask import EVAL_SET

EXPECTED = FIXTURES / "ask_plan_expected.json"
COMPOUND_SET = FIXTURES / "ask_eval_plan_compound.json"  # 복합 WHY K1~K4(추가 검토 1 M2)
CASE_NO = "CASE-2022-000057"  # 평가 요청 예시와 같은 케이스 번호 — 다른 케이스 차단(04)만 판정에 씀


@dataclass
class Row:
    id: str
    n: int
    same: int = 0
    expected: int = 0  # 기대 계획과 같은 회차 수
    failed: int = 0
    diffs: list[str] = field(default_factory=list)  # 다른 회차의 다른 칸 요약
    max_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0


def items() -> list[dict]:
    """48문항 — 세트 파일 순서, id 는 `세트:문항`(18·358 세트와 359 세트의 O1~O4 가 겹침). 계획 전에 코드가 끝내는 C2 는 뺀다."""
    out: list[dict] = []
    for tag, path in (
        ("18", EVAL_SET),
        ("358", judge.PREMISE_SET),
        ("359", judge.GAPS_SET),
        ("362", COMPOUND_SET),
    ):
        out += [
            {**i, "id": f"{tag}:{i['id']}"} for i in json.loads(path.read_text(encoding="utf-8"))["items"]
        ]
    return [i for i in out if not blocked_before_plan(i["question"], CASE_NO)]


def diff(saved: AskPlanOut, got: AskPlanOut, question: str = "") -> str:
    """다른 칸 요약 — `kind A→B` · `사유 A→B` · `묶음 +x -y`(실제로 꺼낸 묶음 기준). 같으면 빈 글자."""
    parts = []
    if got.kind != saved.kind:
        parts.append(f"kind {saved.kind.value}→{got.kind.value}")
    if got.out_of_scope_reason != saved.out_of_scope_reason:
        parts.append(f"사유 {_v(saved.out_of_scope_reason)}→{_v(got.out_of_scope_reason)}")
    have, want = (set(plan_bundles(o, question)) for o in (got, saved))
    added, removed = sorted(have - want), sorted(want - have)
    if added or removed:
        parts.append("묶음 " + " ".join([*(f"+{b}" for b in added), *(f"-{b}" for b in removed)]))
    return " · ".join(parts)


def expected_sig(item_id: str) -> tuple:
    """기대 계획 픽스처 → `_plan_sig` 와 같은 모양(kind · 사유 · 실제로 꺼낸 묶음 집합)."""
    want = json.loads(EXPECTED.read_text(encoding="utf-8"))["plans"][item_id]
    reason = want["out_of_scope_reason"]
    return (
        AskPlanKind(want["kind"]),
        OutOfScopeReason(reason) if reason else None,
        frozenset(want["bundles"]),
    )


def measure(settings: Settings, item: dict, n: int, live: LlmClient) -> Row:
    question = mask_question(item["question"])
    want = expected_sig(item["id"])
    saved = AskLlm(RecordedLlmClient(RECORDED), settings).plan(question, deadline=float("inf")).out
    llm, row = AskLlm(live, settings), Row(item["id"], n)
    for k in range(1, n + 1):
        start = time.monotonic()
        try:
            got = llm.plan(question, deadline=start + settings.ask_budget_s)
        except AiError as exc:
            row.failed += 1
            row.diffs.append(f"{k}회 실패 {exc.code}")
            continue
        row.max_ms = max(row.max_ms, int((time.monotonic() - start) * 1000))
        row.tokens_in, row.tokens_out = row.tokens_in + got.tokens_in, row.tokens_out + got.tokens_out
        row.expected += _plan_sig(got.out, question) == want
        if _plan_sig(got.out, question) == _plan_sig(saved, question):
            row.same += 1
        else:
            row.diffs.append(f"{k}회 {diff(saved, got.out, question)}")
    return row


def main(argv: list[str] | None = None, client: Callable[[Settings], LlmClient] = HttpLlmClient) -> int:
    p = argparse.ArgumentParser(description="질문 답변 계획 흔들림 재기 (docs/str/08)")
    p.add_argument("--n", type=int, default=5, help="문항마다 계획 호출 수(고치기 전 5 · 고친 뒤 10)")
    p.add_argument("--only", help="쉼표로 id 만 (예 18:W2,359:X1)")
    args = p.parse_args(argv)
    settings = get_settings()
    if settings.ai_llm_mock:
        print("ERROR: AI_LLM_MOCK=true — 실제 호출을 위해 false 로 설정", file=sys.stderr)
        return 2
    targets = [i for i in items() if not args.only or i["id"] in set(args.only.split(","))]
    live = client(settings)
    rows = [measure(settings, i, args.n, live) for i in targets]
    _print(rows, settings, args.n)
    return 0 if all(r.same == r.expected == r.n for r in rows) else 3


def _print(rows: list[Row], s: Settings, n: int) -> None:
    print("| # | 같음 | 기대와 같음 | 실패 | 다른 회차 | 최대 ms | 평균 tokens_in | 평균 tokens_out |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        done = max(r.n - r.failed, 1)
        print(
            f"| {r.id} | {r.same}/{r.n} | {r.expected}/{r.n} | {r.failed} | {'; '.join(r.diffs) or '-'} | {r.max_ms} "
            f"| {r.tokens_in // done} | {r.tokens_out // done} |"
        )
    moved = sum(r.same != r.n for r in rows)
    off = sum(r.expected != r.n for r in rows)
    failed = sum(r.failed for r in rows)
    print(
        f"다름 문항 {moved}/{len(rows)} · 기대와 같음 {len(rows) - off}/{len(rows)} · 실패 {failed} · "
        f"호출 {n * len(rows)} (목표: 다름 0 · 기대와 같음 {len(rows)}/{len(rows)} · 실패 0)"
    )
    print(f"설정: 모델 {s.llm_model_generate} · temperature_supported={s.llm_temperature_supported} · "
          f"reasoning_effort={s.llm_reasoning_effort}")  # fmt: skip
    print(f"{ASK_PLAN_PROMPT} sha256 {file_sha256(PROMPTS_DIR / f'{ASK_PLAN_PROMPT}.md')}")


def _v(x) -> str:  # noqa: ANN001
    return "null" if x is None else x.value


if __name__ == "__main__":
    raise SystemExit(main())
