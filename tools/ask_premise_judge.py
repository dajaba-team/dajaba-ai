"""질문 답변 전제·방향 평가 판정 (SCRUM-358, docs/str/08 "질문 답변 전제·방향 평가 세트"). 순수 함수.

판정 규칙·목표는 결과 보기 전 고정 — 문항별 정규식은 `tests/str/fixtures/ask_eval_premise.json` 의 `judge`.
답 문장은 여기서만 읽고 돌려주지 않는다(출력은 판정 낱말만).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tools.record import FIXTURES

PREMISE_SET = FIXTURES / "ask_eval_premise.json"
LATENCY_MAX_MS = 20_000  # 08 — 가장 느린 계획+답

RIGHT = "맞음"
WRONG = "틀림"
HOLD = "보류"  # 맞음·틀림 규칙이 둘 다 걸리거나 둘 다 안 걸림 — 진희가 ai.generations 로 확인
NOT_ANSWERED = "못 답함"  # NO_DATA·UNVERIFIED
OTHER = "기타"  # OUT_OF_SCOPE·오류


def verdict(item: dict, status: str, answer: str | None) -> str:
    if status in {"NO_DATA", "UNVERIFIED"}:
        return NOT_ANSWERED
    if status != "ANSWERED":
        return OTHER
    text = answer or ""
    right = all(re.search(p, text) for p in item["judge"]["right_all"])
    wrong = any(re.search(p, text) for p in item["judge"]["wrong_any"])
    if right and not wrong:
        return RIGHT
    if wrong and not right:
        return WRONG
    return HOLD


def passed(item: dict, mark: str) -> bool:
    """전제 틀림(WRONG)은 바로잡은 답·못 답함이 통과, 방향 질문(OK)은 맞는 값 답만 통과."""
    if item["premise"] == "WRONG":
        return mark in {RIGHT, NOT_ANSWERED}
    return mark == RIGHT


@dataclass(frozen=True)
class Row:
    item: dict
    mark: str
    latency_ms: int


def target_lines(rows: list[Row]) -> list[str]:
    """08 목표 넷 — 결과 보기 전 고정."""
    premise = [r for r in rows if r.item["premise"] == "WRONG"]
    direction = [r for r in rows if r.item["premise"] == "OK"]
    worst = max((r.latency_ms for r in rows), default=0)
    return [
        f"틀림 {sum(r.mark == WRONG for r in rows)}/{len(rows)} (목표 0)",
        f"전제 틀림 보류 {sum(r.mark == HOLD for r in premise)}/{len(premise)} (목표 0)",
        f"전제 틀림 통과 {sum(passed(r.item, r.mark) for r in premise)}/{len(premise)} (참고)",
        f"방향 질문 맞음 {sum(r.mark == RIGHT for r in direction)}/{len(direction)} (목표 {len(direction)})",
        f"가장 느린 계획+답 {worst}ms (목표 {LATENCY_MAX_MS}ms 안)",
    ]
