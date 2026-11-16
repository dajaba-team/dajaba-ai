"""안정화 집계의 한국어 표 렌더링. 본문·금액은 입력에 없다."""

from __future__ import annotations

from typing import Any

CALL_LABELS = {"generate": "생성", "critique": "초안 평가자", "rewrite": "고쳐 쓰기", "judge": "검증 평가자"}
RATE_LABELS = {
    "code_first": "코드 첫 통과율",
    "code_final": "코드 최종 통과율",
    "passed": "검증 PASSED 비율",
    "rewrite_applied": "고쳐 쓰기 적용률",
}


def _consistency_rows(group: dict[str, Any]) -> list[str]:
    """사건별 섹션 종류 수와 숫자·상태 일치를 표로 만든다."""
    lines = [
        "| 일관성 사건 | 섹션별 서로 다른 본문 수 | 숫자 덩이 동일 | 최종 상태 동일 |",
        "|---|---|---|---|",
    ]
    for case, values in group["consistency"].items():
        sections = ", ".join(f"{s}: {n}" for s, n in values["distinct_per_section"].items())
        numbers = "예" if values["numbers_same"] else "아니오"
        status = "예" if values["status_same"] else "아니오"
        lines.append(f"| {case} | {sections or '없음'} | {numbers} | {status} |")
    return lines


def render_group(title: str, group: dict[str, Any]) -> list[str]:
    """한 집계의 일관성·통과율·점수·비용·시간·하루 한도를 표시한다."""
    lines = ["", f"## {title}", "", *_consistency_rows(group), "", "| 통과율 | 값 |", "|---|---:|"]
    lines.extend(f"| {RATE_LABELS[k]} | {v:.1%} |" for k, v in group["pass_rates"].items())
    lines.extend(["", "| 평가자 기준 | 최소 | 중앙 | 최대 |", "|---|---:|---:|---:|"])
    for name, scores in group["judge_scores"].items():
        lines.append(f"| {name} | {scores['min']} | {scores['median']:g} | {scores['max']} |")
    lines.extend(["", "| 비용: 호출 종류 | 토큰 평균 | 토큰 최대 |", "|---|---:|---:|"])
    for kind, label in CALL_LABELS.items():
        cost = group["cost"][kind]
        lines.append(f"| {label} | {cost['tokens_mean']:.2f} | {cost['tokens_max']} |")
    draft = group["cost"]["draft_tokens_mean"]
    verify = group["cost"]["verify_tokens_mean"]
    lines.extend(
        [
            f"| 초안 1건 합계 | {draft:.2f} | — |",
            f"| 검증 1건 합계 | {verify:.2f} | — |",
            f"| 초안 + 검증 1건 합계 | {draft + verify:.2f} | — |",
            "",
            "| 시간: 호출 종류 | p50 (ms) | p95 (ms) | 최대 (ms) |",
            "|---|---:|---:|---:|",
        ]
    )
    for kind, label in CALL_LABELS.items():
        times = group["latency"][kind]
        lines.append(f"| {label} | {times['p50']} | {times['p95']} | {times['max']} |")
    lines.extend(
        ["", "| 하루 처리 가능 건수 | 값 |", "|---|---:|", f"| 초안 + 검증 | {group['daily_capacity']} |"]
    )
    return lines
