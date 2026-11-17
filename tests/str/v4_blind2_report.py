"""재블라인드 집계 결과 md — 승·무·패 · 기준 ①~④ · 회귀(참고) · 틀린 문장 원문."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.str.v4_blind_report import VERDICT_LABELS, WINNER_LABELS, _cell, _wrong_table

if TYPE_CHECKING:
    from tests.str.v4_blind2_reveal import Revealed2


def render_report2(r: Revealed2) -> str:
    from tests.str.v4_blind2_reveal import FIX_MAX_V4, PREFERENCE_MIN, SUPPORT_RATERS

    lines = ["# 재블라인드 결과", "", "| 사건 | 우세 | ④ v4 쪽 정답 평가자 |", "|---|---|---|"]
    lines += [
        f"| {_cell(c)} | {WINNER_LABELS[w]} | {r.support_correct.get(c, 0)} |"
        for c, w in r.case_winner.items()
    ]
    rec = r.record
    lines += [
        "",
        f"승 {rec['v4']} · 무 {rec['none']} · 패 {rec['v2']} (새 사건 {sum(rec.values())}건, v4 기준)",
        "",
        "| 기준 | 충족 | 수치 |",
        "|---|---|---|",
        f"| ① 사실 | {r.fact_ok} | 12쌍 v4 코드 검사 실패 0 + 확인된 틀린 문장 0 |",
        f"| ② 선호 | {r.preference_ok} | v4 우세 {rec['v4']} (≥ {PREFERENCE_MIN}) |",
        f"| ③ 고칠 양 | {r.fix_ok} | v2 {r.fix_mean['v2']:.2f} / v4 {r.fix_mean['v4']:.2f} (v4 ≤ v2, v4 ≤ {FIX_MAX_V4}) |",
        f"| ④ 유형 뒷받침 | {r.support_ok} | 모든 새 사건에서 v4 쪽 정답 ≥ {SUPPORT_RATERS}명 |",
        "",
        f"대조쌍 차이 있음 선택: {r.control_diff_raters}명",
        "",
        "| 회귀(참고, 판정 제외) | 우세 |",
        "|---|---|",
    ]
    lines += [f"| {_cell(c)} | {WINNER_LABELS[w]} |" for c, w in r.regression_winner.items()]
    lines += ["", "| 판정 | 결과 |", "|---|---|", f"| 최종 | {VERDICT_LABELS[r.verdict]} ({r.verdict}) |"]
    lines += _wrong_table(r.wrong_sentences)
    return "\n".join(lines) + "\n"
