"""SCRUM-265 (1/2) — 재블라인드 집계 (손 실행, pytest 수집 X). LLM 0.

기준은 09 2026-11-17 "SCRUM-265 1/2 — 사전 등록" ①②(2/2 카탈로그 변경 전 확정):
① 사실 — 12쌍 v4 전부(회귀·대조 포함) 코드 검사 실패 0 + 확인된 v4 틀린 문장 0
② 선호 — 새 사건 8건 중 사건 다수결(2명 이상 같은 쪽) v4 우세 ≥ 5, 승·무·패 그대로
③ 고칠 양 — 새 사건 8건 평균 v4 ≤ v2 그리고 v4 ≤ FIX_MAX_V4
④ 유형 뒷받침 — v4 쪽 답만, 새 사건 8건 모두에서 SUPPORT_RATERS 명 이상 정답(정답은 사건 파일 칸)
대조쌍 "차이 있음" 2명 이상 → 판정 보류(방향성). 228 집계 함수(`v4_blind_tally`)를 그대로 쓰고 사건만 거름.

사용 (선택 확정 뒤):
    python -m tests.str.v4_blind2_reveal <diag.json> <key.json> <responses.json> [confirmed.json]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from tests.str.v4_blind2_cases import load_cases
from tests.str.v4_blind2_io import load_responses2, result_paths, validate_pairs, validate_run
from tests.str.v4_blind2_report import render_report2
from tests.str.v4_blind_reveal import CONTROL_FLAG_RATERS, MAJORITY_RATERS, Confirmed, Response, WrongSentence
from tests.str.v4_blind_reveal_io import load_confirmed
from tests.str.v4_blind_tally import (
    case_winners,
    collect_wrong_sentences,
    fact_passes,
    mean_fixes,
    validate_responses,
)

Support = Literal["yes", "no", "unknown"]
SUPPORT_VALUES = ("yes", "no", "unknown")
SUPPORT_RATERS = 2  # 사건마다 v4 쪽 정답 평가자 수 하한
RATER_COUNT = 3  # 평가자 명단 고정(09 사전 등록) — 빠지거나 넘치면 거절
FIX_MAX_V4 = 2.0  # ③ v4 평균 상한
PREFERENCE_MIN = 5  # ② 새 사건 8건 중 v4 우세 하한


@dataclass(frozen=True)
class Response2(Response):
    support_a: Support | None = None  # "이 초안에 따르면 유형 분류가 거래 내역으로 뒷받침됩니까?" — A 초안
    support_b: Support | None = None
    run_id: str | None = None  # 생성 실행 묶음 — 키·진단과 같아야 함


@dataclass(frozen=True)
class Revealed2:
    case_winner: dict[str, str]  # 새 사건만
    record: dict[str, int]  # {"v4": 승, "v2": 패, "none": 무}
    fact_ok: bool
    preference_ok: bool
    fix_mean: dict[str, float]
    fix_ok: bool
    support_correct: dict[str, int]  # 새 사건 → v4 쪽 정답 평가자 수
    support_ok: bool
    control_diff_raters: int
    verdict: str  # directional > candidate(넷 다) > not_met
    regression_winner: dict[str, str]  # 참고용
    wrong_sentences: list[WrongSentence]


def _validate_support(responses: list[Response2]) -> None:
    """평가자 3명 고정 + support 값 셋. 쌍 전부 답했는지는 228 validate_responses 가 평가자별로 봄."""
    if len({r.rater for r in responses}) != RATER_COUNT:
        raise ValueError("평가자는 정확히 3명이어야 함")
    for r in responses:
        if r.support_a not in SUPPORT_VALUES or r.support_b not in SUPPORT_VALUES:
            raise ValueError("support_a·support_b 는 yes/no/unknown 이어야 함")


def _support(responses: list[Response2], pairs: dict, answers: dict[str, list[str]]) -> dict[str, int]:
    correct = dict.fromkeys(answers, 0)
    for r in responses:
        pair = pairs[r.pair_no]
        if pair["control"] or pair["case_id"] not in answers:
            continue
        side = "A" if pair["A"] == "v4" else "B"
        correct[pair["case_id"]] += (r.support_a if side == "A" else r.support_b) in answers[pair["case_id"]]
    return correct


def reveal2(
    responses: list[Response2], key: dict[str, Any], diag: dict[str, Any], doc: dict[str, Any],
    confirmed: Confirmed | None = None,
) -> Revealed2:  # fmt: skip
    validate_run(key, diag, responses)
    validate_pairs(key, diag, doc)
    pairs = {p["pair_no"]: p for p in key["pairs"]}
    metrics = {p["pair_no"]: p for p in diag["pairs"]}
    validate_responses(responses, pairs, metrics)  # type: ignore[arg-type]
    _validate_support(responses)
    answers = {c["case_id"]: c["answer"] for c in doc["cases"] if c["role"] == "judged"}
    judged_pairs = {n: p for n, p in pairs.items() if p["control"] or p["case_id"] in answers}
    judged = [r for r in responses if r.pair_no in judged_pairs]
    winners = case_winners(judged, judged_pairs, MAJORITY_RATERS)  # type: ignore[arg-type]
    record = {side: sum(w == side for w in winners.values()) for side in ("v4", "v2", "none")}
    regression = {n: p for n, p in pairs.items() if n not in judged_pairs}
    reg_responses = [r for r in responses if r.pair_no in regression]
    wrong = collect_wrong_sentences(responses, pairs, confirmed or set())  # type: ignore[arg-type]
    fix_mean = mean_fixes(judged, judged_pairs)  # type: ignore[arg-type]
    correct = _support(responses, pairs, answers)
    control = len({r.rater for r in responses if pairs[r.pair_no]["control"] and r.choice != "same"})
    checks = (
        fact_passes(wrong, pairs, metrics),
        record["v4"] >= PREFERENCE_MIN,
        fix_mean["v4"] <= fix_mean["v2"] and fix_mean["v4"] <= FIX_MAX_V4,
        all(n >= SUPPORT_RATERS for n in correct.values()),
    )
    verdict = "directional" if control >= CONTROL_FLAG_RATERS else "candidate" if all(checks) else "not_met"
    reg_winner = case_winners(reg_responses, regression, MAJORITY_RATERS) if reg_responses else {}  # type: ignore[arg-type]
    return Revealed2(winners, record, checks[0], checks[1], fix_mean, checks[2], correct, checks[3], control,
                     verdict, reg_winner, wrong)  # fmt: skip


def render_revealed2_md(revealed: Revealed2) -> str:
    return render_report2(revealed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="재블라인드 선택 확정 뒤 집계")
    for name in ("diag", "key", "responses"):
        parser.add_argument(name, type=Path)
    parser.add_argument("confirmed", type=Path, nargs="?")
    args = parser.parse_args(argv)
    inputs = [p for p in (args.diag, args.key, args.responses, args.confirmed) if p is not None]
    out_json, out_md = result_paths(args.key, inputs)
    diag, key = (json.loads(p.read_text(encoding="utf-8")) for p in (args.diag, args.key))
    result = reveal2(load_responses2(args.responses), key, diag, load_cases(), load_confirmed(args.confirmed))
    out_json.write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_revealed2_md(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
