"""SCRUM-268 — judge_v4 사전 기준 1·2 판정 (09 "SCRUM-268 judge_v4 사전 기준 — 측정 전" 그대로). LLM 0.

기준 1: 평가자마다 기준 본문 목표 항목이 n 중 MIN_HITS 회 이상 ≥ 통과 기준일 때만 그 사례를 판정에 넣고, 주입 본문 목표
항목이 n 중 MIN_HITS 회 이상 < 통과 기준이면 잡음. 비율 = 잡은 사례 / 주입 수, 충족 = judge_v4 ≥ judge_v3. 참고 사례 판정 밖.
기준 2: 뒤집기 NO_UNSUPPORTED n 회 모두 ≤ 2 = 잡음, 원래 초안 대조가 n 중 2회 이상 ≥ 3 일 때만 판정(추가 검토 2차 —
LLM_FAILED 로 세던 것을 대체, 다른 항목 실패는 근거 아님). 코드 검사 실패 뒤집기는 판정 불가.
평가자 실패·코드 검사 실패 회차는 점수가 없어 잡음도 ≥ 4 도 아님. 표본 완전성·실행 조건은 254 와 같은 규칙.
추가 검토 1차(09 같은 날 "측정 전 기준 보충"): 근거가 없으면 통과가 아니라 판정 불가(criterion_met False + 이유) —
기준 1 점수 있는 회차 부족·judge_v3 비율 0, 기준 2 코드 검사 통과 뒤집기가 기대 18건 전부가 아님.
"""

from __future__ import annotations

from typing import Any

from aml_ai.str.domain.constants import JUDGE_PASS_SCORE, JUDGE_PROMPT, JUDGE_PROMPT_V4
from tests.str.injection_live_support import EXPECTS
from tests.str.judge_v4_criteria import C1_INJECTIONS, CONTROL_PREFIX, FLIP_PREFIX

MIN_HITS = 2  # 09 — n=3 중 2회 이상
# 추가 검토 2차 — 기준 2 목표 항목. judge_v4 루브릭에서 블록과 반대 = 1점, 기존 "FACTS 에 없는 정황" = 3점
C2_TARGET = "NO_UNSUPPORTED_CLAIM"
FLIP_CAUGHT_MAX = 2  # 뒤집기 잡음 = n 회 모두 이 점수 이하
CONTROL_MIN = 3  # 대조(원래 초안)가 n 중 MIN_HITS 회 이상 이 점수 이상일 때만 판정
# 09 SCRUM-268 사전 기준 — 실행 때 실제 쓴 값과 비교, 하나라도 다르면 exploratory
REGISTERED: dict[str, Any] = {"prompts": [JUDGE_PROMPT, JUDGE_PROMPT_V4], "votes": 3, "pass_score": 4, "n": 3,
                              "c1_injections": len(C1_INJECTIONS), "c2_flips": 18, "c2_controls": 18}  # fmt: skip


def run_conditions(
    *,
    prompts: list[str],
    votes: int,
    pass_score: int,
    n: int,
    c1_injections: int,
    c2_flips: int,
    c2_controls: int,
) -> dict[str, Any]:
    return {"prompts": prompts, "votes": votes, "pass_score": pass_score, "n": n,
            "c1_injections": c1_injections, "c2_flips": c2_flips, "c2_controls": c2_controls}  # fmt: skip


def mode_of(conditions: dict[str, Any]) -> tuple[str, list[str]]:
    diff = [k for k, v in REGISTERED.items() if conditions.get(k) != v]
    return ("exploratory" if diff else "registered"), diff


def _hits(records: list[dict[str, Any]], check: str, ok: Any) -> int:
    return sum(1 for r in records if check in r["scores"] and ok(r["scores"][check]))


def _scored(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """점수 있는 회차만 — VERIFY_UNAVAILABLE·CODE_FAILED 는 scores 가 빔."""
    return [r for r in records if r["scores"]]


def _judge_c1(records: list[dict[str, Any]], prompt: str) -> tuple[dict[str, Any], list[str], list[str]]:
    """한 평가자 — (결과, 판정 불가 이유, 기준 본문 탈락 이유). 목표 항목은 EXPECTS(기록이 없어도 앎)."""
    mine = [r for r in records if r["criterion"] == 1 and r["prompt"] == prompt]
    base = _scored([r for r in mine if r["role"] == "base"])
    insufficient = [] if len(base) >= MIN_HITS else [f"c1:insufficient:{prompt}:base"]
    caught: list[int] = []
    base_ok: dict[str, bool] = {}
    excluded: list[str] = []
    for k in C1_INJECTIONS:
        target = EXPECTS[k]["target"]
        inj = _scored([r for r in mine if r["case_id"] == f"c1:{prompt}:inject_{k}"])
        if len(inj) < MIN_HITS:
            insufficient.append(f"c1:insufficient:{prompt}:inject_{k}")
        if insufficient:
            continue  # 판정 불가 — 탈락·잡음을 셀 근거가 없음
        base_ok[target] = _hits(base, target, lambda s: s >= JUDGE_PASS_SCORE) >= MIN_HITS
        if not base_ok[target]:
            excluded.append(f"c1:excluded:{prompt}:inject_{k}:{target}")  # 잡지 못함으로 셈
        elif _hits(inj, target, lambda s: s < JUDGE_PASS_SCORE) >= MIN_HITS:
            caught.append(k)
    result = {"caught": caught, "rate": len(caught) / len(C1_INJECTIONS), "base_ok": base_ok}
    return result, insufficient, excluded


def criterion1(records: list[dict[str, Any]]) -> dict[str, Any]:
    """추가 검토 1차 순서: (a) 점수 부족 → 판정 불가 (b) 기준 본문 탈락은 이유에 (c) judge_v3 0 → 판정 불가 (d) 비교."""
    out: dict[str, Any] = {}
    reasons: list[str] = []
    undecidable = False
    for prompt in (JUDGE_PROMPT, JUDGE_PROMPT_V4):
        out[prompt], insufficient, excluded = _judge_c1(records, prompt)
        reasons += insufficient + excluded
        undecidable = undecidable or bool(insufficient)
    if not undecidable and out[JUDGE_PROMPT]["rate"] == 0:
        reasons.append(f"c1:no_baseline:{JUDGE_PROMPT}")
        undecidable = True
    met = not undecidable and out[JUDGE_PROMPT_V4]["rate"] >= out[JUDGE_PROMPT]["rate"]
    return out | {"undecidable": undecidable, "reasons": reasons, "met": met}


def _by_case(records: list[dict[str, Any]], role: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        if r["criterion"] == 2 and r["role"] == role:
            out.setdefault(r["case_id"], []).append(r)
    return out


def _flip_caught(runs: list[dict[str, Any]], n: int) -> bool:
    """n 회 모두 점수가 있고 목표 항목 ≤ FLIP_CAUGHT_MAX — 평가자 실패 회차가 있으면 잡지 못함."""
    return len(runs) == n and all(
        C2_TARGET in r["scores"] and r["scores"][C2_TARGET] <= FLIP_CAUGHT_MAX for r in runs
    )


def _control_reason(runs: list[dict[str, Any]], sid: str) -> str | None:
    """대조(원래 초안)가 판정 근거가 되는지 — 점수 부족·이미 낮음이면 판정 불가 이유."""
    scored = _scored(runs)
    if len(scored) < MIN_HITS:
        return f"c2:control_insufficient:{sid}"
    if _hits(scored, C2_TARGET, lambda s: s >= CONTROL_MIN) < MIN_HITS:
        return f"c2:control_low:{sid}"
    return None


def criterion2(records: list[dict[str, Any]], n: int, expected_flips: list[str]) -> dict[str, Any]:
    """추가 검토 2차: 잡음 = 목표 항목(NO_UNSUPPORTED) n 회 모두 ≤ 2, 대조가 n 중 2회 이상 ≥ 3 일 때만 판정.
    코드 검사 실패·대조 부족·대조 낮음은 판정 불가. 충족 = 기대 18건 전부 판정 + 전부 잡음. 다른 항목은 근거 아님."""
    flips, controls = _by_case(records, "flip"), _by_case(records, "control")
    code_failed = sorted(c for c, rs in flips.items() if any(r["status"] == "CODE_FAILED" for r in rs))
    reasons = [f"c2:code_failed:{c}" for c in code_failed]
    caught: list[str] = []
    not_caught: list[str] = []
    for f in sorted(set(flips) | set(expected_flips)):
        sid = f.removeprefix(FLIP_PREFIX)
        reason = None if f in code_failed else _control_reason(controls.get(CONTROL_PREFIX + sid, []), sid)
        if f in code_failed or reason:
            reasons += [reason] if reason else []
            continue
        (caught if _flip_caught(flips.get(f, []), n) else not_caught).append(f)
    decided = set(caught) | set(not_caught)
    undecidable = decided != set(expected_flips) or len(expected_flips) != REGISTERED["c2_flips"]
    if undecidable and not reasons:
        reasons.append("c2:not_all_flips_evaluated")
    met = not undecidable and not not_caught
    return {"evaluated": len(set(flips) - set(code_failed)), "code_failed": code_failed, "caught": caught,
            "not_caught": not_caught, "undecidable": undecidable, "reasons": reasons, "met": met}  # fmt: skip


def _completeness(records: list[dict[str, Any]], expected: list[str], n: int) -> list[str]:
    runs: dict[str, list[int]] = {}
    for r in records:
        runs.setdefault(r["case_id"], []).append(r["run"])
    reasons = [f"missing:{c}" for c in expected if c not in runs]
    reasons += [f"runs:{c}" for c in expected if c in runs and sorted(runs[c]) != list(range(1, n + 1))]
    return reasons + [f"unexpected:{c}" for c in runs if c not in expected]


def verdict(records: list[dict[str, Any]], expected: list[str], conditions: dict[str, Any]) -> dict[str, Any]:
    """조건 다름 → exploratory(criterion_met None). 표본 불완전 → 둘 다 미달. 판정 불가 → 그 기준 False +
    `undecidable` + 이유. expected = dry-run 과 같은 생성기 사례 id."""
    mode, reasons = mode_of(conditions)
    if mode == "exploratory":
        return {"mode": mode, "criterion_met": None, "reasons": reasons}
    n = conditions["n"]
    incomplete = _completeness(records, expected, n)
    c1 = criterion1(records)
    c2 = criterion2(records, n, [c for c in expected if c.startswith(FLIP_PREFIX)])
    met = {"c1": not incomplete and c1["met"], "c2": not incomplete and c2["met"]}
    return {"mode": mode, "criterion_met": met, "undecidable": {"c1": c1["undecidable"], "c2": c2["undecidable"]},
            "reasons": incomplete + c1["reasons"] + c2["reasons"], "c1": c1, "c2": c2}  # fmt: skip
