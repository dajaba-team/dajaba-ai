"""안정화 측정의 일관성·비율·호출 비용 집계. 본문을 받지 않는 순수 함수."""

from __future__ import annotations

from collections import defaultdict
from math import ceil
from statistics import mean, median
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tests.str.stability_support import RunRecord

KINDS = ("generate", "critique", "rewrite", "judge")


def _consistency(records: list[RunRecord]) -> dict[str, Any]:
    """사건마다 섹션 종류 수와 숫자·상태 일치를 비교한다."""
    groups: dict[str, list[RunRecord]] = defaultdict(list)
    for record in records:
        groups[record.case_id].append(record)
    out = {}
    for case, runs in groups.items():
        sections = dict.fromkeys(s for r in runs for s in r.section_hashes)
        out[case] = {
            "distinct_per_section": {s: len({r.section_hashes.get(s) for r in runs}) for s in sections},
            "numbers_same": len({r.number_set_hash for r in runs}) == 1,
            "status_same": len({r.final_status for r in runs}) == 1,
        }
    return out


def _pass_rates(records: list[RunRecord]) -> dict[str, float]:
    """초안 실패는 코드 검사 통과에 포함하지 않는다."""
    count = len(records)
    counts = {
        "code_first": sum(r.final_status != "DRAFT_FAILED" and not r.code_failures_first for r in records),
        "code_final": sum(r.final_status != "DRAFT_FAILED" and not r.code_failures_final for r in records),
        "passed": sum(r.final_status == "PASSED" for r in records),
        "rewrite_applied": sum(r.rewrite_applied for r in records),
    }
    return {name: value / count if count else 0.0 for name, value in counts.items()}


def _judge_scores(records: list[RunRecord]) -> dict[str, Any]:
    """평가 점수가 있는 회차만 기준별로 집계한다."""
    scores: dict[str, list[int]] = defaultdict(list)
    for record in records:
        for name, score in (record.judge_scores or {}).items():
            scores[name].append(score)
    return {
        name: {"min": min(values), "median": float(median(values)), "max": max(values)}
        for name, values in scores.items()
    }


def _cost_latency(records: list[RunRecord]) -> tuple[dict[str, Any], dict[str, Any]]:
    """종류별 실제 호출과 회차별 합계는 서로 다른 분모로 평균 낸다."""
    cost: dict[str, Any] = {}
    latency = {}
    calls = [c for r in records for c in r.calls]
    for kind in KINDS:
        tokens = [c.tokens_in + c.tokens_out for c in calls if c.kind == kind]
        times = sorted(c.latency_ms for c in calls if c.kind == kind)
        cost[kind] = {
            "tokens_mean": float(mean(tokens)) if tokens else 0.0,
            "tokens_max": max(tokens, default=0),
        }
        latency[kind] = {
            "p50": times[ceil(len(times) * 0.5) - 1] if times else 0,
            "p95": times[ceil(len(times) * 0.95) - 1] if times else 0,
            "max": max(times, default=0),
        }
    for label, kinds in (("draft", KINDS[:3]), ("verify", ("judge",))):
        total = sum(c.tokens_in + c.tokens_out for c in calls if c.kind in kinds)
        cost[f"{label}_tokens_mean"] = total / len(records) if records else 0.0
    return cost, latency


def aggregate(records: list[RunRecord], daily_token_budget: int) -> dict[str, Any]:
    """전체 회차와 검색 성공 회차에 같은 모양의 집계를 적용한다."""
    cost, latency = _cost_latency(records)
    tokens = cost["draft_tokens_mean"] + cost["verify_tokens_mean"]
    return {
        "consistency": _consistency(records),
        "pass_rates": _pass_rates(records),
        "judge_scores": _judge_scores(records),
        "cost": cost,
        "latency": latency,
        "daily_capacity": int(daily_token_budget // tokens) if tokens else 0,
    }
