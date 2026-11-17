"""SCRUM-268 — judge_v4 사전 기준 1·2 측정 (손 실행, pytest 수집 X). 09 "SCRUM-268 judge_v4 사전 기준 — 측정 전".

사례 31(`judge_v4_criteria.build_criteria_cases` — 기준 1 judge_v3 6 · judge_v4 7, 기준 2 뒤집기 18). 시연 후보 경보는
ops 읽기만(`demo_alerts`). 사례 × 회차마다 그 사례 평가자(표 3, verify 와 같은 설정)를 새로 만듦.

사용 (CLI dry-run — LLM 호출 0, ops 읽기만):
    uv run --frozen --extra dev python -m tests.str.judge_v4_criteria_live --dry-run --demo-alerts 7,48 \\
        --demo-requests tests/str/recorded/_tmp/demo_requests_7-48.json
사용 (진희 터미널, AI_LLM_MOCK=false): 위에서 `--dry-run` → `--live --n 3`
결과: `_tmp/judge_v4_criteria_dry_<stamp>.json` · 회차 기록 `_tmp/judge_v4_criteria_<stamp>.jsonl` ·
판정 `_tmp/judge_v4_criteria_<stamp>.json`(jsonl 을 다시 읽어 만듦)
"""

from __future__ import annotations

import argparse
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE, JUDGE_SCHEMA_RETRY, JUDGE_VOTES
from aml_ai.str.infrastructure.judge import Judge, JudgeResult
from tests.str.demo_alerts import DEFAULT_DEMO_ALERTS, demo_facts, load_exports, parse_alert_ids
from tests.str.judge_stability_v4_live import _write
from tests.str.judge_stability_v4_run import read_records
from tests.str.judge_stability_verify import _wrap_call_with_retry
from tests.str.judge_v4_criteria import C1_INJECTIONS, CriteriaCase, build_criteria_cases, dry_run
from tests.str.judge_v4_criteria_run import run_cases
from tests.str.judge_v4_criteria_tally import REGISTERED, mode_of, run_conditions, verdict


def _cases(ids: list[int], requests: Path) -> list[CriteriaCase]:
    from aml_ai.shared.db import get_session

    exports = load_exports(requests, ids)
    session = next(get_session())
    cases = build_criteria_cases([(f"demo_{i}", demo_facts(session, exports[i]["request"])) for i in ids])
    session.rollback()  # 읽기만
    return cases


def _live(cases: list[CriteriaCase], n: int, meta: dict[str, Any], stamp: str) -> None:
    settings = get_settings()
    http = HttpLlmClient(settings)

    def make_judge(prompt: str) -> tuple[Judge, list[JudgeResult]]:
        judge = Judge(http, settings, prompt_name=prompt, votes=JUDGE_VOTES, schema_retry=JUDGE_SCHEMA_RETRY)
        ballots: list[JudgeResult] = []
        _wrap_call_with_retry(judge, ballots, threading.Lock())
        return judge, ballots

    from tests.str.injection_live_support import TMP_DIR

    out = TMP_DIR / f"judge_v4_criteria_{stamp}.jsonl"
    run_cases(cases, n, make_judge, settings.verify_budget_s, out)
    v = verdict(read_records(out), [c.case_id for c in cases], meta["conditions"])
    print(f"사전 기준 mode={v['mode']}: {v['criterion_met']} {v['reasons']}")
    _write(f"judge_v4_criteria_{stamp}.json", meta | v | {"records_file": out.name})


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="judge_v4 사전 기준 1·2 측정")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--live", action="store_true")
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--demo-alerts", default=",".join(map(str, DEFAULT_DEMO_ALERTS)))
    p.add_argument("--demo-requests", type=Path, required=True)
    a = p.parse_args(argv)
    cases = _cases(parse_alert_ids(a.demo_alerts), a.demo_requests)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    # 실제 쓴 값 — 평가자 프롬프트는 사례에서, 표 수·통과 기준은 verify 와 같은 상수, n 은 인자
    conditions = run_conditions(prompts=sorted({c.prompt for c in cases}), votes=JUDGE_VOTES,
                                pass_score=JUDGE_PASS_SCORE, n=a.n,
                                c1_injections=sum(c.role == "inject" for c in cases) // len(REGISTERED["prompts"]),
                                c2_flips=sum(c.role == "flip" for c in cases), c2_controls=sum(c.role == "control" for c in cases))  # fmt: skip
    mode_, reasons = mode_of(conditions)
    meta = {"cases": len(cases), "conditions": conditions, "mode": mode_, "mode_reasons": reasons,
            "c1_injections": list(C1_INJECTIONS), "llm_client": HttpLlmClient.__name__}  # fmt: skip
    print(f"mode={mode_} {reasons} cases={len(cases)} n={a.n}")
    if a.dry_run:
        rows = dry_run(cases)
        for r in rows:
            print(f"{r['case_id']:<32} {r['prompt']} code_fail={r['code_check_failures']} "
                  f"sha256={r['user_sha256'][:16]}")  # fmt: skip
        _write(f"judge_v4_criteria_dry_{stamp}.json", meta | {"rows": rows})
    else:
        _live(cases, a.n, meta, stamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
