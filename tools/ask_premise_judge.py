"""질문 답변 평가 판정 — 전제·방향(SCRUM-358) · 사각지대(SCRUM-359), docs/str/08 두 절. 순수 함수.

판정 규칙·목표는 결과 보기 전 고정 — 문항별 정규식은 세트 파일(`ask_eval_premise.json`·`ask_eval_gaps.json`)의 `judge`.
예외 하나(SCRUM-362 ★B3-5, 진희 — v4 결과를 본 뒤): 틀림 규칙은 이름표를 뺀 LLM 글에(`verdict` 의 `written`).
358 문항은 `premise`, 359 문항은 `expect`(ANSWER·BLOCK)로 통과를 가른다 — 358 규칙은 359 때문에 바뀌지 않는다.
답 문장은 여기서만 읽고 돌려주지 않는다(출력은 판정 낱말만).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tools.record import FIXTURES

PREMISE_SET = FIXTURES / "ask_eval_premise.json"
GAPS_SET = FIXTURES / "ask_eval_gaps.json"
COMPOUND_SET = FIXTURES / "ask_eval_plan_compound.json"  # 복합 WHY K1~K4(SCRUM-362 추가 검토 1)
GAPS_HOLD_MAX = 2  # 08 — 359 보류 상한
LATENCY_MAX_MS = 20_000  # 08 — 가장 느린 계획+답

RIGHT = "맞음"
WRONG = "틀림"
HOLD = "보류"  # 맞음·틀림 규칙이 둘 다 걸리거나 둘 다 안 걸림 — 진희가 ai.generations 로 확인
NOT_ANSWERED = "못 답함"  # NO_DATA·UNVERIFIED
OTHER = "기타"  # OUT_OF_SCOPE·오류
MISSING_BUNDLE = "묶음 빠짐"  # 복합 WHY — ANSWERED 인데 기대 묶음 하나의 자리표가 없음


def verdict(
    item: dict,
    status: str,
    answer: str | None,
    written: str | None = None,
    conflict: bool = False,
    unclear: bool = False,
) -> str:
    """맞음 규칙은 읽는 사람이 보는 글(`answer` — 렌더링한 답, 이름표 포함), 틀림 규칙은 LLM 이 쓴 글(`written` — 자리표를
    이름표 없이 값만 넣은 글, `tools.ask_judge_text`). `written` 이 없으면(자리표 없는 v1·v2) 같은 글(SCRUM-362 ★B3-5, 08)."""
    if status in {"NO_DATA", "UNVERIFIED"}:
        return NOT_ANSWERED
    if status != "ANSWERED":
        return OTHER
    if (
        conflict
    ):  # 같은 절의 LLM 방향 낱말이 자리표 키의 방향과 어긋남(`ask_judge_text`, 추가 검토 1 H4 · 2 M1)
        return WRONG
    if unclear:  # 한 절에 입금·출금 낱말이 섞여 연결 불명확 → 사람 확인(추가 검토 2 M1)
        return HOLD
    shown = answer or ""
    llm = shown if written is None else written
    right = all(re.search(p, shown) for p in item["judge"]["right_all"])
    wrong = any(re.search(p, llm) for p in item["judge"]["wrong_any"])
    if right and not wrong:
        return RIGHT
    if wrong and not right:
        return WRONG
    return HOLD


def passed(item: dict, mark: str, status: str = "") -> bool:
    """358: 전제 틀림(WRONG)은 바로잡은 답·못 답함이 통과, 방향 질문(OK)은 맞는 값 답만 통과.

    359: ANSWER 는 맞음만, BLOCK 은 맞음·못 답함·범위 밖(`status` OUT_OF_SCOPE)이 통과 — 틀린 값을 내보내지 않음.
    """
    if "expect" in item:
        if item["expect"] == "ANSWER":
            return mark == RIGHT
        return mark in {RIGHT, NOT_ANSWERED} or status == "OUT_OF_SCOPE"
    if item["premise"] == "WRONG":
        return mark in {RIGHT, NOT_ANSWERED}
    return mark == RIGHT


@dataclass(frozen=True)
class Row:
    item: dict
    mark: str
    latency_ms: int
    status: str = ""


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


def target_lines_gaps(rows: list[Row]) -> list[str]:
    """08 359 목표 (A) 엄격 — 결과 보기 전 고정."""
    answer = [r for r in rows if r.item["expect"] == "ANSWER"]
    worst = max((r.latency_ms for r in rows), default=0)
    return [
        f"틀림 {sum(r.mark == WRONG for r in rows)}/{len(rows)} (목표 0)",
        f"보류 {sum(r.mark == HOLD for r in rows)}/{len(rows)} (목표 {GAPS_HOLD_MAX} 이하)",
        f"ANSWER 맞음 {sum(r.mark == RIGHT for r in answer)}/{len(answer)} (목표 {len(answer)})",
        f"통과 {sum(passed(r.item, r.mark, r.status) for r in rows)}/{len(rows)} (참고)",
        f"가장 느린 계획+답 {worst}ms (목표 {LATENCY_MAX_MS}ms 안)",
    ]


def compound_mark(item: dict, status: str, cites: list[str]) -> str:
    """복합 WHY(08 — SCRUM-362 추가 검토 1): ANSWERED 이고 기대 묶음마다 그 묶음 자리표 키를 1개 이상 썼으면 맞음."""
    from aml_ai.str.domain.ask_bundles import key_in_bundle

    if status in {"NO_DATA", "UNVERIFIED"}:
        return NOT_ANSWERED
    if status != "ANSWERED":
        return OTHER
    want = item["expected"]["bundles"]
    return RIGHT if all(any(key_in_bundle(c, b) for c in cites) for b in want) else MISSING_BUNDLE


def target_lines_compound(rows: list[Row]) -> list[str]:
    """08 복합 WHY 목표 — 결과 보기 전 고정."""
    worst = max((r.latency_ms for r in rows), default=0)
    n = len(rows)
    return [
        f"ANSWERED {sum(r.status == 'ANSWERED' for r in rows)}/{n} (목표 {n})",
        f"UNVERIFIED {sum(r.status == 'UNVERIFIED' for r in rows)}/{n} (목표 0)",
        f"두 묶음 자리표 {sum(r.mark == RIGHT for r in rows)}/{n} (목표 {n})",
        f"가장 느린 계획+답 {worst}ms (목표 {LATENCY_MAX_MS}ms 안)",
    ]


SETS = {
    "premise": (PREMISE_SET, target_lines),
    "gaps": (GAPS_SET, target_lines_gaps),
    "compound": (COMPOUND_SET, target_lines_compound),
}
