"""확정 뒤 집계 결과와 확인할 문장 원문을 한국어 표로 표시한다."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.str.v4_blind_reveal import Revealed, WrongSentence

VERDICT_LABELS = {
    "candidate": "전환 후보",
    "not_met": "미달",
    "directional": "방향성(판정 보류)",
}
WINNER_LABELS = {"v2": "v2", "v4": "v4", "none": "우세 없음(none)"}


def _cell(value: object) -> str:
    """원문의 줄바꿈과 세로줄이 표 구조를 바꾸지 않도록 표시한다."""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", r"\|")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
    )


def _wrong_table(sentences: list[WrongSentence]) -> list[str]:
    lines = ["", "| 평가자 | 쌍 | 사건 | 쪽 | 버전 | 원문 | 확인 여부 |", "|---|---|---|---|---|---|---|"]
    for w in sentences:
        cells = (
            w.rater,
            w.pair_no,
            w.case_id,
            w.side,
            w.version,
            w.text,
            "확인됨" if w.confirmed else "미확인",
        )
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    if not sentences:
        lines.extend(["", "보고된 틀린 문장 없음."])
    return lines


def render_report(revealed: Revealed) -> str:
    lines = ["# 비교 결과", "", "| 사건 | 우세 |", "|---|---|"]
    lines.extend(
        f"| {_cell(case_id)} | {WINNER_LABELS[winner]} |" for case_id, winner in revealed.case_winner.items()
    )
    lines.extend(
        [
            "",
            "| 기준 | 충족 | 수치 |",
            "|---|---|---|",
            f"| ① 사실 | {revealed.fact_ok} | v4 코드 검사 실패 0 + 확인된 틀린 문장 0 |",
            f"| ② 선호 | {revealed.preference_ok} | {revealed.v4_wins}/{revealed.cases} 사건에서 v4 우세 |",
            f"| ③ 고칠 양 | {revealed.fix_ok} | v2 {revealed.fix_mean['v2']:.2f} / v4 {revealed.fix_mean['v4']:.2f} |",
            "",
            "| 대조쌍 | 평가자 수 |",
            "|---|---|",
            f"| 차이 있음 선택 | {revealed.control_diff_raters} |",
            "",
            "| 평가자 | 다수결 일치율 |",
            "|---|---|",
        ]
    )
    lines.extend(f"| {_cell(rater)} | {ratio:.1%} |" for rater, ratio in revealed.rater_agreement.items())
    verdict = VERDICT_LABELS[revealed.verdict]
    lines.extend(["", "| 판정 | 결과 |", "|---|---|", f"| 최종 | {verdict} ({revealed.verdict}) |"])
    lines.extend(_wrong_table(revealed.wrong_sentences))
    return "\n".join(lines) + "\n"
