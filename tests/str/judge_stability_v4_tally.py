"""SCRUM-254 ★L-1 — v4 측정 집계 (docs/str/08 "평가자 흔들림 — v4 초안", 09 SCRUM-254 사전 기준). LLM 0.

기록 1개 = 사건 1회(verify 경로 3표 중앙값). 사건마다 PASSED/LLM_FAILED 횟수 · 항목별 중앙값·최소 · 떨어진 항목과
평가자 comment 원문. 사전 기준 = v4 사건 전부가 n 회 모두 PASSED(v2 대조는 판정 밖).
"""

from __future__ import annotations

import statistics
from typing import Any

from aml_ai.str.domain.constants import JUDGE_PASS_SCORE

_STATUS_KEY = {
    "PASSED": "passed",
    "LLM_FAILED": "failed",
    "VERIFY_UNAVAILABLE": "unavailable",
    "CODE_FAILED": "code_failed",
}


def tally(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in sorted(records, key=lambda x: (x["case_id"], x["run"])):
        s = out.setdefault(r["case_id"], {"kind": r["kind"], "passed": 0, "failed": 0, "unavailable": 0, "code_failed": 0,
                                          "scores": {}, "failed_items": [],
                                          "tokens_in": 0, "tokens_out": 0, "wall_clock_ms": 0})  # fmt: skip
        s[_STATUS_KEY.get(r["status"], "failed")] += (
            1  # VERIFY_UNAVAILABLE·CODE_FAILED 는 PASSED 아님으로 따로 셈
        )
        for check, score in r["scores"].items():
            s["scores"].setdefault(check, []).append(score)
            if score < JUDGE_PASS_SCORE:
                s["failed_items"].append({"run": r["run"], "check": check, "score": score,
                                          "comment": r.get("comments", {}).get(check, "")})  # fmt: skip
        for k in ("tokens_in", "tokens_out", "wall_clock_ms"):
            s[k] += r.get(k, 0)
    for s in out.values():
        scores = s.pop("scores")
        s["checks"] = {c: {"median": statistics.median_low(v), "min": min(v)} for c, v in scores.items()}
    return out


def meets_criterion(summary: dict[str, dict[str, Any]], n: int) -> bool:
    """v4 사건 전부가 n 회 모두 PASSED — 평가자 실패(VERIFY_UNAVAILABLE)·코드 검사 실패도 PASSED 아님."""
    v4 = [s for s in summary.values() if s["kind"] == "v4"]
    return bool(v4) and all(
        s["passed"] == n and s["failed"] + s["unavailable"] + s["code_failed"] == 0 for s in v4
    )


def render_table(summary: dict[str, dict[str, Any]]) -> str:
    lines = ["| 사건 | 종류 | PASSED | 평가자 실패 | 떨어진 항목(회차·점수) |", "|---|---|---|---|---|"]
    for case_id, s in summary.items():
        runs = s["passed"] + s["failed"] + s["unavailable"] + s["code_failed"]
        failed = ", ".join(f"{f['check']}(run {f['run']}·{f['score']})" for f in s["failed_items"]) or "—"
        lines.append(f"| {case_id} | {s['kind']} | {s['passed']}/{runs} | {s['unavailable']} | {failed} |")
    return "\n".join(lines) + "\n"


REGISTERED_N = 3  # 09 SCRUM-254 사전 기준 — 회차
REGISTERED_V4 = 18  # 09 SCRUM-254 사전 기준 — v4 사건(시연 후보 2 포함). v2 대조 1 은 판정 밖
# 09 SCRUM-254 사전 기준 ① 의 실행 조건(추가 검토 4차) — 실행 때 실제 쓴 값과 비교. 고정값(중앙값 집계·항목 5개·
# 코드 검사 → 평가자 순서·실제 LLM 클라이언트)은 하네스 코드라 여기 없음
REGISTERED: dict[str, Any] = {"prompt": "judge_v3", "votes": 3, "pass_score": 4, "n": REGISTERED_N,
                              "v4_cases": REGISTERED_V4}  # fmt: skip


def run_conditions(*, prompt: str, votes: int, pass_score: int, n: int, v4_cases: int) -> dict[str, Any]:
    """실행 때 실제 쓴 값 — 결과 meta `conditions` 에 그대로."""
    return {"prompt": prompt, "votes": votes, "pass_score": pass_score, "n": n, "v4_cases": v4_cases}


def mode_of(conditions: dict[str, Any]) -> tuple[str, list[str]]:
    """등록 값과 다른 조건 이름(등록 표 순서) — 하나라도 있으면 exploratory. 시작 mode·최종 판정 둘 다 이 함수."""
    diff = [k for k, v in REGISTERED.items() if conditions.get(k) != v]
    return ("exploratory" if diff else "registered"), diff


def verdict(
    records: list[dict[str, Any]], expected: list[tuple[str, str]], conditions: dict[str, Any]
) -> dict[str, Any]:
    """판정 전 실행 조건(추가 검토 4차)·표본 완전성(3차) 검사. expected = dry-run 과 같은 생성기의 (case_id, kind).

    조건이 등록 값과 다름 → mode=exploratory, criterion_met=None(이유 = 조건 이름).
    빠진 사건 · 사건마다 회차 번호가 정확히 1..n 이 아님(중복·누락) · 목록 밖 사건 → 미달.
    """
    mode, reasons = mode_of(conditions)
    if mode == "exploratory":
        return {"mode": mode, "criterion_met": None, "reasons": reasons}
    n = conditions["n"]
    runs: dict[str, list[int]] = {}
    for r in records:
        runs.setdefault(r["case_id"], []).append(r["run"])
    for case_id, _ in expected:
        if case_id not in runs:
            reasons.append(f"missing:{case_id}")
        elif sorted(runs[case_id]) != list(range(1, n + 1)):
            reasons.append(f"runs:{case_id}")
    reasons += [f"unexpected:{c}" for c in runs if c not in dict(expected)]
    met = not reasons and meets_criterion(tally(records), n)
    return {"mode": mode, "criterion_met": met, "reasons": reasons}
