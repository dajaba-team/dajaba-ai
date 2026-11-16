"""SCRUM-228 (2/2) 1단계 — 블라인드 선택 확정 뒤 키로 A/B → v2/v4 매핑·집계 (손 실행, pytest 수집 X).

LLM 0. 기준은 09 2026-11-17 2/2 1단계 ★A 줄(결과 보기 전 확정):
① 사실 — v4 전 사건 코드 검사 실패 0(진단 파일) + 평가자가 적은 v4 틀린 문장 중 확인된 것 0
   (reveal 이 틀린 문장을 원문과 함께 목록으로 내고, 진희가 확인 칸을 채움 — 미확인은 안 셈)
② 선호 — 대조쌍 제외 사건의 과반(n 건 중 n//2 + 1 이상)에서 사건 단위 다수결 v4 우세.
   사건 단위 다수결 = 평가자 MAJORITY_RATERS(2)명 이상이 같은 쪽을 고른 사건만 그쪽 우세, 나머지는 우세 없음
   (차이 없음은 표 아님 — 1:0:2 도 우세 없음)
③ 고칠 양 — 고칠 문장 수 평균 v4 ≤ v2
대조쌍에서 "차이 있음"(A 또는 B)을 고른 평가자가 2명 이상이면 판정 보류("방향성").

사용 (진희 선택 확정 뒤):
    python -m tests.str.v4_blind_reveal <v4_blind_diag_<tag>.json> <v4_blind_key_<tag>.json> <responses.json> \
        [confirmed.json]
출력: 같은 폴더 `v4_blind_revealed_<tag>.json` + `.md` (틀린 문장 목록 포함 — 확인 칸을 채운 confirmed.json 으로 다시 돌림)
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from tests.str.v4_blind_report import render_report
from tests.str.v4_blind_reveal_io import load_confirmed, load_responses
from tests.str.v4_blind_tally import (
    agreement,
    case_winners,
    collect_wrong_sentences,
    fact_passes,
    mean_fixes,
    validate_responses,
)

Choice = Literal["A", "B", "same"]
Verdict = Literal["candidate", "not_met", "directional"]
CONTROL_FLAG_RATERS = 2  # 대조쌍에서 차이 있음을 고른 평가자가 이 수 이상이면 판정 보류
MAJORITY_RATERS = 2  # 사건 단위 다수결 — 같은 쪽을 고른 평가자가 이 수 이상일 때만 그쪽 우세
Confirmed = set[tuple[str, int, str, str]]  # (rater, pair_no, side "A"|"B", text) — 진희가 확인한 틀린 문장


@dataclass(frozen=True)
class Response:
    rater: str
    pair_no: int  # md 의 "쌍 N"
    choice: Choice
    fix_a: int  # 그대로 쓰려면 고칠 문장 수
    fix_b: int
    wrong_a: tuple[str, ...] = ()  # 평가자가 적은 틀린 문장(사실과 다름) 원문
    wrong_b: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class WrongSentence:
    """평가자가 적은 틀린 문장 — 원문과 함께 목록으로 내고, 진희 확인(AI 보조 확인 표기) 뒤 confirmed 만 ① 에 셈."""

    rater: str
    pair_no: int
    case_id: str
    side: str  # "A" | "B"
    version: str  # "v2" | "v4" (키로 푼 값 — revealed 에만)
    text: str
    confirmed: bool = False


@dataclass(frozen=True)
class Revealed:
    case_winner: dict[str, Literal["v2", "v4", "none"]]  # 대조쌍 제외 case_id → 다수결(2명 이상), 아니면 none
    v4_wins: int
    cases: int  # 대조쌍 제외 사건 수
    fact_ok: bool  # ①
    preference_ok: bool  # ②
    fix_ok: bool  # ③
    fix_mean: dict[str, float]  # {"v2": …, "v4": …} 대조쌍 제외
    control_diff_raters: int  # 대조쌍에서 A·B 를 고른 평가자 수
    verdict: Verdict  # directional(대조쌍 규칙) > candidate(①②③ 모두) > not_met
    rater_agreement: dict[str, float]  # 평가자별 다수결 일치율(대조쌍 제외, 표 없는 사건 제외)
    wrong_sentences: list[WrongSentence]  # 틀린 문장 전부(확인 여부 포함)


def reveal(
    responses: list[Response], key: dict[str, Any], diag: dict[str, Any], confirmed: Confirmed | None = None
) -> Revealed:
    """응답 + 키(쌍 → case·A/B 버전·대조쌍) + 진단(쌍별 A/B 코드 검사 실패 수) + 확인된 틀린 문장 → 집계·판정."""
    pairs = {p["pair_no"]: p for p in key["pairs"]}
    metrics = {p["pair_no"]: p for p in diag["pairs"]}
    validate_responses(responses, pairs, metrics)
    winners = case_winners(responses, pairs, MAJORITY_RATERS)
    wins = sum(winner == "v4" for winner in winners.values())
    wrong_sentences = collect_wrong_sentences(responses, pairs, confirmed or set())
    fact_ok = fact_passes(wrong_sentences, pairs, metrics)
    preference_ok = wins >= len(winners) // 2 + 1
    fix_mean = mean_fixes(responses, pairs)
    fix_ok = fix_mean["v4"] <= fix_mean["v2"]
    control_diff = len({r.rater for r in responses if pairs[r.pair_no]["control"] and r.choice != "same"})
    verdict: Verdict = "not_met"
    if control_diff >= CONTROL_FLAG_RATERS:
        verdict = "directional"
    elif fact_ok and preference_ok and fix_ok:
        verdict = "candidate"
    return Revealed(
        winners,
        wins,
        len(winners),
        fact_ok,
        preference_ok,
        fix_ok,
        fix_mean,
        control_diff,
        verdict,
        agreement(responses, pairs, winners),
        wrong_sentences,
    )


def render_revealed_md(revealed: Revealed) -> str:
    """사건별 우세·기준 ①~③·대조쌍·평가자 일치율·판정과 틀린 문장 원문을 표시한다."""
    return render_report(revealed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="선택 확정 뒤 블라인드 결과 집계")
    parser.add_argument("diag", type=Path)
    parser.add_argument("key", type=Path)
    parser.add_argument("responses", type=Path)
    parser.add_argument("confirmed", type=Path, nargs="?")
    args = parser.parse_args(argv)
    diag = json.loads(args.diag.read_text(encoding="utf-8"))
    key = json.loads(args.key.read_text(encoding="utf-8"))
    result = reveal(load_responses(args.responses), key, diag, load_confirmed(args.confirmed))
    tag = args.diag.stem.removeprefix("v4_blind_diag_")
    output = args.diag.with_name(f"v4_blind_revealed_{tag}.json")
    output.write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    output.with_suffix(".md").write_text(render_revealed_md(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
