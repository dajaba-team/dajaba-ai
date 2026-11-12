"""SCRUM-207 — 평가자 흔들림 1단계 측정 (손 실행, pytest 수집 X).

왜: 같은 원본 본문을 초안 안 평가자는 TYPOLOGY_CONSISTENT 5, 검증 평가자는 3 으로 본 경우가 생김
(docs/str/09 SCRUM-147). 두 경로 입력이 같은지와 같은 경로 안 분포를 N 회로 측정한다.

사용 (CLI dry-run — 호출 0, user 문자열 sha256 비교만):
    uv run --frozen --extra dev python -m tests.str.judge_stability_live --dry-run

사용 (★L-1 라이브 — 진희 터미널, AI_LLM_MOCK=false):
    uv run --frozen --extra dev python -m tests.str.judge_stability_live --live \\
        --cases 12,23 --n 5 --prompt judge_v3

사용 (★L-2 재측정 — 207 적용 뒤 verify 경로 N=3 병렬 집계):
    uv run --frozen --extra dev python -m tests.str.judge_stability_live --verify-votes \\
        --cases 12,23 --n 5 --prompt judge_v3

결과:
- dry-run      → 표준출력 요약 + `_tmp/judge_stability_dry_<stamp>.json`
- live         → `_tmp/judge_stability_live_<stamp>.json` (단일 호출 raw — ★L-1)
- verify-votes → `_tmp/judge_stability_verify_<stamp>.json` (집계 결과 — ★L-2, 1 iteration = 3 병렬 호출)
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.shared.schemas.str.narrative_version import llm_output_model
from aml_ai.str.domain.constants import JUDGE_MAX_TOKENS
from tests.str.injection_live_support import TMP_DIR, model_slot
from tests.str.judge_input_support import CASE_FIXTURES
from tests.str.judge_stability_paths import PathInput, build_path_inputs, first_diff_block
from tests.str.judge_stability_verify import run_verify_votes

log = logging.getLogger(__name__)


def _print_source_table(a: PathInput, b: PathInput) -> None:
    print("code paths (develop, 2026-11-12):")
    print(f"  {a.label}:")
    for key, src in a.source.items():
        print(f"    {key:14s} ← {src}")
    print(f"  {b.label}:")
    for key, src in b.source.items():
        print(f"    {key:14s} ← {src}")


def run_dry(cases: list[int], prompt_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {"mode": "dry-run", "prompt": prompt_name, "cases": {}}
    first = True
    for case in cases:
        a, b = build_path_inputs(case, prompt_name)
        if first:
            _print_source_table(a, b)
            first = False
        same = a.user_sha256 == b.user_sha256
        case_out: dict[str, Any] = {
            "draft_user_sha256": a.user_sha256,
            "verify_user_sha256": b.user_sha256,
            "same": same,
            "note": "왕복 뒤에도 같음" if same else "왕복에서 달라짐",
            "fact_keys_count": len(a.fact_keys),
            "fact_keys_order_same": a.fact_keys == b.fact_keys,
            "source": {"draft_inside": a.source, "verify": b.source},
        }
        if not same:
            case_out["first_diff"] = first_diff_block(a.user, b.user)
        out["cases"][case] = case_out
        print(
            f"[dry] case={case} prompt={prompt_name} same={same} "
            f"draft={a.user_sha256[:8]} verify={b.user_sha256[:8]} keys={len(a.fact_keys)} "
            f"keys_order_same={a.fact_keys == b.fact_keys}"
        )
        if not same:
            print(case_out["first_diff"])
    return out


def _invoke_once(system: str, user: str, prompt_name: str) -> dict[str, Any]:
    settings = get_settings()
    model = settings.llm_model_judge or settings.llm_model_generate
    t0 = time.monotonic()
    res = HttpLlmClient(settings).complete_json(
        system=system, user=user, model=model, max_tokens=JUDGE_MAX_TOKENS, tag=prompt_name
    )
    latency_ms = int((time.monotonic() - t0) * 1000)
    parsed = llm_output_model(prompt_name).model_validate_json(res.text)
    scores = {c.check.value: c.score for c in parsed.checks}
    status = "PASSED" if min(scores.values()) >= 4 else "LLM_FAILED"
    return {
        "scores": scores,
        "status": status,
        "model": res.model,
        "tokens_in": res.tokens_in,
        "tokens_out": res.tokens_out,
        "latency_ms": latency_ms,
    }


def run_live(cases: list[int], n: int, prompt_name: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        a, b = build_path_inputs(case, prompt_name)
        for path_name, inp in (("draft_inside", a), ("verify", b)):
            for run in range(1, n + 1):
                r = _invoke_once(inp.system, inp.user, prompt_name)
                r.update({
                    "case": case,
                    "path": path_name,
                    "run": run,
                    "prompt": prompt_name,
                    "user_sha256": inp.user_sha256,
                })  # fmt: skip
                print(
                    f"[live] case={case} path={path_name} run={run} "
                    f"status={r['status']} tokens_in={r['tokens_in']} tokens_out={r['tokens_out']} "
                    f"latency_ms={r['latency_ms']}"
                )
                results.append(r)
    return results


def save(payload: Any, kind: str) -> Path:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    slot = model_slot()
    path = TMP_DIR / f"judge_stability_{kind}_{slot}_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="SCRUM-207 judge stability 1단계 측정")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="LLM 호출 0 — user 문자열 sha256 비교")
    mode.add_argument("--live", action="store_true", help="실제 호출(★L-1 단일 호출 raw) — 진희 터미널")
    mode.add_argument(
        "--verify-votes",
        action="store_true",
        help="★L-2 — verify 경로 Judge(votes=JUDGE_VOTES) 집계 결과 저장",
    )
    parser.add_argument("--cases", default=",".join(str(c) for c in CASE_FIXTURES),
                        help="쉼표 구분 case 번호(기본 12,23)")  # fmt: skip
    parser.add_argument("--n", type=int, default=5, help="live 모드 회차(기본 5)")
    parser.add_argument("--prompt", default="judge_v3",
                        help="평가자 프롬프트(judge_v2|judge_v3)")  # fmt: skip
    args = parser.parse_args()

    cases = [int(c.strip()) for c in args.cases.split(",") if c.strip()]
    for c in cases:
        if c not in CASE_FIXTURES:
            raise SystemExit(f"unknown case: {c} (지원: {sorted(CASE_FIXTURES)})")

    if args.dry_run:
        payload = run_dry(cases, args.prompt)
        path = save(payload, "dry")
        print(f"[dry] saved → {path}")
        return 0

    if args.verify_votes:
        results = run_verify_votes(cases, args.n, args.prompt)
        path = save(results, "verify")
        print(f"[verify-votes] saved → {path}")
        return 0

    results = run_live(cases, args.n, args.prompt)
    path = save(results, "live")
    print(f"[live] saved → {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
