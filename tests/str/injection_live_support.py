"""injection live 하네스 (SCRUM-127) — judge-only 5 케이스 (7·8·10·11·12) × N × prompt(v2/v3) × 모델.

기준 본문 = `recorded/narrative_v2/a976ae216c7fb1bb.json` + `fixtures/facts_fan_in.json`.
결과 → `tests/str/recorded/_tmp/injection_live_<tag>_<stamp>.json` (gitignore).
`pytest -m live` 로 진희 터미널에서만 돌림. CI 는 `-m 'not live'` 라 안 돎.

generate 케이스(9·14·23) 는 지시서 판정에서 "참고 — 판정 안 씀" 이라 이 iteration 에서는 skip
(판정 조건: 모델② 기준 ① 12번 N/N PASSED ② 7·8·10·11 대상 항목 N/N ≤3).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.shared.schemas.str import Facts, RevisedNarrativeSection
from aml_ai.shared.schemas.str.narrative_version import llm_output_model
from aml_ai.str.domain.constants import JUDGE_MAX_TOKENS
from tests.str.judge_input_support import CASE_FIXTURES, render_judge_user_for

__all__ = [
    "CASE_FIXTURES",  # 재export — 호환 (judge_stability_live.py 가 여기서 import)
    "FIXTURES",
    "RECORDED_V2",
    "TMP_DIR",
    "render_judge_user_for",
]

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDED_V2 = REPO_ROOT / "tests/str/recorded/narrative_v2/a976ae216c7fb1bb.json"
FIXTURES = REPO_ROOT / "tests/str/fixtures"
TMP_DIR = REPO_ROOT / "tests/str/recorded/_tmp"

JUDGE_ONLY = (7, 8, 10, 11, 12)

EXPECTS: dict[int, dict[str, Any]] = {
    7: {"target": "NO_SPECULATION", "op": "le3"},
    8: {"target": "NO_UNSUPPORTED_CLAIM", "op": "le3"},
    10: {"target": "TYPOLOGY_CONSISTENT", "op": "le3"},
    11: {"target": "FIVE_W_ONE_H_COMPLETE", "op": "le3"},
    12: {"target": "all", "op": "ge4"},
}


def base_narrative() -> list[RevisedNarrativeSection]:
    data = json.loads(RECORDED_V2.read_text(encoding="utf-8"))
    inner = json.loads(data["text"])
    return [RevisedNarrativeSection.model_validate(s) for s in inner["narrative"]]


def base_facts() -> Facts:
    return Facts.model_validate(json.loads((FIXTURES / "facts_fan_in.json").read_text(encoding="utf-8")))


def _replace(narr: list[RevisedNarrativeSection], section: str, text: str) -> list[RevisedNarrativeSection]:
    return [s.model_copy(update={"text": text}) if s.section.value == section else s for s in narr]


def _append(narr: list[RevisedNarrativeSection], section: str, suffix: str) -> list[RevisedNarrativeSection]:
    return [
        s.model_copy(update={"text": s.text + " " + suffix}) if s.section.value == section else s
        for s in narr
    ]


def inject_7(narr: list[RevisedNarrativeSection]) -> list[RevisedNarrativeSection]:
    """GROUNDS 에 "마약 대금으로 보인다" (08 주입 7 원문)."""
    return _append(narr, "GROUNDS", "본 거래는 마약 대금으로 보인다.")


def inject_8(narr: list[RevisedNarrativeSection]) -> list[RevisedNarrativeSection]:
    """METHOD 에 "매주 월요일마다" (08 주입 8 원문, facts 에 없음)."""
    return _append(narr, "METHOD", "매주 월요일마다 반복적으로 입금됨.")


def inject_10(narr: list[RevisedNarrativeSection]) -> list[RevisedNarrativeSection]:
    """METHOD·GROUNDS 를 FAN_OUT 설명으로 교체 (facts 는 FAN_IN)."""
    fan_out = "대상 계좌에서 여러 상대 계좌로 자금이 분산되는 FAN_OUT 유형으로 보임."
    narr = _replace(narr, "METHOD", fan_out + " 출금 집중이 확인됨.")
    return _replace(narr, "GROUNDS", fan_out + " 다수 상대 계좌로의 분산이 검토 지표임.")


def inject_11(narr: list[RevisedNarrativeSection]) -> list[RevisedNarrativeSection]:
    """OPINION 섹션 text 를 "자료 없음" 만 남김 — 평가자만 단독 호출."""
    return _replace(narr, "OPINION", "자료 없음")


def inject_12(narr: list[RevisedNarrativeSection]) -> list[RevisedNarrativeSection]:
    """기준 본문 그대로 (정상 회귀)."""
    return narr


INJECTIONS: dict[int, Callable[[list[RevisedNarrativeSection]], list[RevisedNarrativeSection]]] = {
    7: inject_7,
    8: inject_8,
    10: inject_10,
    11: inject_11,
    12: inject_12,
}


@dataclass
class JudgeRun:
    scores: dict[str, int]
    status: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


def invoke_judge(
    facts: Facts,
    narrative: list[RevisedNarrativeSection],
    prompt_name: str,
) -> JudgeRun:
    settings = get_settings()
    system, user, _ = render_judge_user_for(facts, narrative, prompt_name)
    model = settings.llm_model_judge or settings.llm_model_generate
    t0 = time.monotonic()
    res = HttpLlmClient(settings).complete_json(
        system=system, user=user, model=model, max_tokens=JUDGE_MAX_TOKENS, tag=prompt_name
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    parsed = llm_output_model(prompt_name).model_validate_json(res.text)
    scores = {c.check.value: c.score for c in parsed.checks}
    status = "PASSED" if min(scores.values()) >= 4 else "LLM_FAILED"
    return JudgeRun(
        scores=scores,
        status=status,
        model=res.model,
        tokens_in=res.tokens_in,
        tokens_out=res.tokens_out,
        latency_ms=latency_ms,
    )


def ok(scores: dict[str, int], expect: dict[str, Any]) -> bool:
    target, op = expect["target"], expect["op"]
    if target == "all":
        return all(s >= 4 for s in scores.values())
    s = scores[target]
    return {"le3": s <= 3, "ge4": s >= 4, "eq5": s == 5}[op]


def run_judge_only_case(case: int, n: int, prompt_name: str) -> list[dict[str, Any]]:
    narr = INJECTIONS[case](base_narrative())
    facts = base_facts()
    expect = EXPECTS[case]
    out: list[dict[str, Any]] = []
    for run in range(1, n + 1):
        r = invoke_judge(facts, narr, prompt_name)
        out.append(
            {
                "case": case,
                "run": run,
                "judge_prompt": prompt_name,
                "judge_model": r.model,
                "scores": r.scores,
                "status": r.status,
                "latency_ms": r.latency_ms,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "expect": expect,
                "ok": ok(r.scores, expect),
            }
        )
    return out


def model_slot() -> str:
    """현재 설정의 judge 모델이 생성 모델과 같으면 `m2`(판정 비교용, SCRUM-92), 다르면 `m1`(판정 기준).

    파일 이름에 모델 이름 자체를 넣지 않고 slot 만 넣음 — 두 번 실행해도 파일이 안 덮어씀.
    """
    s = get_settings()
    judge = s.llm_model_judge or s.llm_model_generate
    return "m2" if judge == s.llm_model_generate else "m1"


def save_results(all_results: list[dict[str, Any]], tag: str) -> Path:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    slot = model_slot()
    path = TMP_DIR / f"injection_live_{tag}_{slot}_{stamp}.json"
    path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
