"""SCRUM-308 ② 리랭커 판정 — 순수 계산 (docs/str/10 "청크 맥락·리랭커·컷오프 판정" ②, 기준 커밋 87aef09).

초안 경로 정답 = 등급 ≥ 1 · `db_tagged=true`. 지표 = 4유형 macro precision@3(분모 3) · 유형별 hit@3.
회차마다: precision@3(리랭커) − (원래 순서) ≥ +0.10 · hit@3 하락 없음 · 호출 시간 p95 ≤ 5초 · 형식 실패율 ≤ 10%.
**두 회차 모두** 넘어야 통과. 숫자는 결과 보기 전 커밋한 기준 그대로 — 여기서 바꾸지 않는다. DB·LLM 0.
"""

from __future__ import annotations

import math
from typing import Any

from tests.str.rag_eval_v3_hybrid_support import DIGITS, JUDGED_TYPES, V3_DIR

RESULT_FILE = V3_DIR / "result_308_rerank.json"
DRY_RESULT_FILE = V3_DIR / "result_308_rerank_dry.json"
TOP = 3  # RAG_TOP_K
PRECISION_GAIN_MIN = 0.10  # ② 4유형 평균 precision@3 오름 하한
P95_MAX_MS = 5000.0  # ② 리랭커 호출 시간 p95 상한(정답 있는 질의, 회차별)
FAIL_RATE_MAX = 0.10  # ② 형식 실패율 상한(원래 순서로 돌아간 호출 / 호출 수)
ROUNDS = 2  # ② 같은 후보에 리랭커 2회, 두 회차 모두 넘어야


def _r(x: float) -> float:
    return round(x, DIGITS)


def metrics(rows: list[dict[str, Any]], answers: dict[str, set[str]]) -> dict[str, Any]:
    """rows = [{typology, top: [chunk_id …]}] → 유형별 {n, precision3, hit3} + 4유형 평균(반올림 전 값으로 macro)."""
    per: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        expected = answers.get(row["typology"] or "", set())
        if not expected:
            continue
        top = set(row["top"][:TOP])
        acc = per.setdefault(row["typology"], {"precision3": [], "hit3": []})
        acc["precision3"].append(len(top & expected) / TOP)
        acc["hit3"].append(1.0 if top & expected else 0.0)
    raw = {t: {m: sum(v) / len(v) for m, v in acc.items()} for t, acc in per.items()}
    judged = [raw[t]["precision3"] for t in JUDGED_TYPES if t in raw]
    return {
        "types": {t: {"n": len(per[t]["hit3"]), **{m: _r(x) for m, x in v.items()}} for t, v in raw.items()},
        "mean_precision3": _r(sum(judged) / len(judged)) if judged else None,
    }


def p95(ms: list[float]) -> float | None:
    """최근접 순위(nearest-rank) p95 — 정렬 뒤 ⌈0.95·n⌉ 번째."""
    if not ms:
        return None
    ordered = sorted(ms)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


def round_verdict(
    base: dict[str, Any], rr: dict[str, Any], call_ms: list[float], failed: int, calls: int
) -> dict[str, Any]:
    """`call_ms` = 정답 있는 질의의 호출 시간(p95) · `failed`/`calls` = 회차 전체 리랭커 대상 중 폴백(실패율, 추가 검토 1)."""
    gain = _r(rr["mean_precision3"] - base["mean_precision3"])
    drops = [t for t in JUDGED_TYPES if _r(base["types"][t]["hit3"] - rr["types"][t]["hit3"]) > 0]
    latency = p95(call_ms)
    fail_rate = _r(failed / calls) if calls else None
    checks = {
        "precision_gain": gain >= PRECISION_GAIN_MIN,
        "no_hit_drop": not drops,
        "p95": latency is not None and latency <= P95_MAX_MS,
        "fail_rate": fail_rate is not None and fail_rate <= FAIL_RATE_MAX,
    }
    return {"gain": gain, "hit_drops": drops, "p95_ms": latency, "calls": calls, "failed": failed,
            "fail_rate": fail_rate, "checks": checks, "passed": all(checks.values())}  # fmt: skip


def verdict(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    """두 회차 모두 넘어야 통과 — 회차 수가 다르면 판정 안 함."""
    if len(rounds) != ROUNDS:
        return {"judged": False, "reason": f"회차 {len(rounds)} ≠ {ROUNDS}", "adopt": False}
    return {
        "judged": True,
        "rounds_passed": [r["passed"] for r in rounds],
        "adopt": all(r["passed"] for r in rounds),
    }


def final_verdict(per_round: list[dict[str, Any]], *, dry: bool) -> dict[str, Any]:
    """최종 판정 — dry 는 판정 안 함 · 응답 모델명 없는 응답이 있거나 두 회차 전체 응답 모델이 2종 이상이면 판정 안 함(추가 검토 2·3)."""
    base = verdict(per_round)
    models = {m for r in per_round for m in r.get("response_models", [])}
    if dry:
        return {**base, "judged": False, "adopt": False, "reason": "dry — 가짜 벡터·가짜 리랭커"}
    if None in models:  # 모델명 없는 응답은 단일 모델 증거가 아님(추가 검토 3)
        return {**base, "judged": False, "adopt": False, "reason": "응답 모델명이 없는 응답이 있음"}
    if len(models) > 1:
        return {
            **base,
            "judged": False,
            "adopt": False,
            "reason": f"응답 모델 {len(models)}종 — 한 모델로 판정해야 함",
        }
    return base


def response_models(rnd: dict[str, dict]) -> list[str | None]:
    """응답을 받은 호출(성공·거절·형식 실패)의 응답 모델 — 모델명 없는 응답은 None 으로 셈(요청 모델로 안 채움)."""
    found = {r["model"] for r in rnd.values() if r.get("responded")}
    return sorted(found, key=lambda m: (m is None, m or ""))
