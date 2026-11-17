"""SCRUM-254 ★L-1 — v4 초안 검증 평가자 측정 (손 실행, pytest 수집 X). 사전 기준 09 "SCRUM-254 ★L-1 사전 기준".

사건 19(`judge_stability_v4.build_cases`, 시연 후보 경보는 ops 읽기만 — `demo_alerts`). 실제 verify 와 같게
코드 검사 5종 → 전부 통과면 Judge(votes=3) 중앙값. 세 표 raw 점수·평가자 comment 원문 보존(로그 아님, `_tmp` 파일).

사용 (CLI dry-run — LLM 호출 0, ops 읽기만):
    uv run --frozen --extra dev python -m tests.str.judge_stability_v4_live --dry-run --demo-alerts 7,48 \\
        --demo-requests tests/str/recorded/_tmp/demo_requests_7-48.json
사용 (진희 터미널, AI_LLM_MOCK=false):
    uv run --frozen --extra dev python -m tests.str.judge_stability_v4_live --live --n 3 --demo-alerts 7,48 \\
        --demo-requests tests/str/recorded/_tmp/demo_requests_7-48.json
결과: `_tmp/judge_stability_v4_dry_<stamp>.json` · 회차 기록 `_tmp/judge_stability_v4_<stamp>.jsonl`(회차마다 이어 씀) ·
요약 `_tmp/judge_stability_v4_<stamp>.json` + 표준출력 표·사전 기준 판정(jsonl 을 다시 읽어 만듦)
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE, JUDGE_PROMPT, JUDGE_SCHEMA_RETRY, JUDGE_VOTES
from aml_ai.str.infrastructure.judge import Judge, JudgeResult
from tests.str.demo_alerts import DEFAULT_DEMO_ALERTS, demo_facts, load_exports, parse_alert_ids
from tests.str.injection_live_support import TMP_DIR
from tests.str.judge_stability_v4 import V4Case, build_cases, dry_run
from tests.str.judge_stability_v4_run import read_records, run_cases
from tests.str.judge_stability_v4_tally import mode_of, render_table, run_conditions, tally, verdict
from tests.str.judge_stability_verify import _wrap_call_with_retry


def _write(name: str, body: dict[str, Any]) -> None:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    (TMP_DIR / name).write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"→ {name}")


def _cases(ids: list[int], requests: Path) -> list[V4Case]:
    """시연 후보는 내보낸 요청 → app_ai 로 facts(읽기만). `--demo-alerts` 와 id 집합이 다르면 거절."""
    from aml_ai.shared.db import get_session

    exports = load_exports(requests, ids)
    session = next(get_session())
    cases = build_cases([(f"demo_{i}", demo_facts(session, exports[i]["request"])) for i in ids])
    session.rollback()  # 읽기만
    return cases


def _dry(cases: list[V4Case], prompt: str, meta: dict[str, Any], stamp: str) -> None:
    rows = dry_run(cases, prompt)
    for r in rows:
        print(
            f"{r['case_id']:<28} {r['kind']} code_fail={r['code_check_failures']} sha256={r['user_sha256'][:16]}"
        )
    _write(f"judge_stability_v4_dry_{stamp}.json", meta | {"rows": rows})


def _live(cases: list[V4Case], prompt: str, n: int, meta: dict[str, Any], stamp: str) -> None:
    settings = get_settings()
    http = HttpLlmClient(settings)

    def make_judge() -> tuple[Judge, list[JudgeResult]]:
        judge = Judge(
            http, settings, prompt_name=prompt, votes=JUDGE_VOTES, schema_retry=JUDGE_SCHEMA_RETRY
        )  # verify 와 같게
        ballots: list[JudgeResult] = []
        _wrap_call_with_retry(judge, ballots, threading.Lock())
        return judge, ballots

    out = TMP_DIR / f"judge_stability_v4_{stamp}.jsonl"  # 회차마다 이어 씀
    run_cases(cases, n, make_judge, settings.verify_budget_s, out)
    records = read_records(out)  # 표·판정은 기록 파일을 다시 읽어
    summary = tally(records)
    print(render_table(summary))
    v = verdict(
        records, [(c.case_id, c.kind) for c in cases], meta["conditions"]
    )  # 실행 조건·표본 → 등록/탐색
    label = {True: "충족", False: "미달", None: "판정 안 함(탐색 실행)"}[v["criterion_met"]]
    print(f"사전 기준 mode={v['mode']}: {label} {v['reasons']}")
    _write(f"judge_stability_v4_{stamp}.json", meta | v | {"summary": summary, "records_file": out.name})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="v4 초안 검증 평가자 측정")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--prompt", default=JUDGE_PROMPT)
    p.add_argument("--demo-alerts", default=",".join(map(str, DEFAULT_DEMO_ALERTS)))
    p.add_argument("--demo-requests", type=Path, required=True)  # demo_alerts.sql 읽기 전용 내보내기(_tmp)
    a = p.parse_args(argv)
    ids = parse_alert_ids(a.demo_alerts)
    cases = _cases(ids, a.demo_requests)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    v4 = sum(c.kind == "v4" for c in cases)
    # 실제 쓴 값 — 평가자 표 수·통과 기준은 하네스가 읽는 상수(verify 와 같은 값), 프롬프트·n 은 인자
    conditions = run_conditions(
        prompt=a.prompt, votes=JUDGE_VOTES, pass_score=JUDGE_PASS_SCORE, n=a.n, v4_cases=v4
    )
    mode, reasons = mode_of(conditions)  # 최종 판정(verdict)과 같은 함수
    meta = {"demo_alerts": ids, "cases": len(cases), "conditions": conditions, "llm_client": HttpLlmClient.__name__,
            "mode": mode, "mode_reasons": reasons}  # fmt: skip
    print(f"mode={mode} {reasons} cases={len(cases)} v4={v4} n={a.n} prompt={a.prompt}")
    if a.dry_run:
        _dry(cases, a.prompt, meta, stamp)
    else:
        _live(cases, a.prompt, a.n, meta, stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
