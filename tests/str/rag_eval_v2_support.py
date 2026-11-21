"""SCRUM-275 평가 세트 공용 — 질의 → facts, 판정 (docs/str/10 "평가 세트"·"판정 기준", 09 2026-11-19).

판정 숫자는 정답을 보기 전에 09·10 에 커밋된 값 — 여기서 바꾸지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aml_ai.shared.schemas.str import Facts

FIXTURES = Path(__file__).parent / "fixtures"  # tests.conftest 안 씀 — 컨테이너(pytest 없음)에서도 import
EVAL_DIR = Path(__file__).parent / "rag_eval_v2"
OVERRIDE_KEYS = frozenset({"industry", "model_signals", "direction", "payment_formats", "counterparty_banks"})
VERDICT_RATIO_MIN = 0.75  # ① 보류용 채운 칸 중 정답 비율 하한
VERDICT_MIN_SLOTS = 6  # ④ 보류용 채운 칸이 이보다 적으면 판정 안 함
ANSWER_GRADE_MIN = 1  # 정답 = grade ≥ 1


def load_queries(split: str) -> list[dict[str, Any]]:
    return json.loads((EVAL_DIR / f"queries_{split}.json").read_text(encoding="utf-8"))["queries"]


def build_facts(query: dict[str, Any]) -> Facts:
    """base 픽스처 + 범주 칸 overrides → Facts(model_validate). 결제 방식을 바꾸면 방식별 건수는 비움."""
    return facts_from_data(json.loads((FIXTURES / query["base"]).read_text(encoding="utf-8")), query)


def facts_from_data(data: dict[str, Any], query: dict[str, Any]) -> Facts:
    """이미 읽은 base 픽스처 `data`(바꿈 — 복사본을 넘길 것)에 overrides → Facts. SCRUM-308-2 가 검증한 바이트로 씀."""
    over = query["overrides"]
    if set(over) - OVERRIDE_KEYS:
        raise ValueError(f"override keys: {sorted(set(over) - OVERRIDE_KEYS)}")
    data["typology"] = query["typology"]
    for key in ("model_signals", "direction", "counterparty_banks"):
        if key in over:
            data[key] = over[key]
    if "payment_formats" in over:
        data["payment_formats"] = over["payment_formats"]
        data["payment_format_counts"] = []
    if "industry" in over and data.get("customer"):
        data["customer"]["industry"] = over["industry"]
    return Facts.model_validate(data)


@dataclass(frozen=True)
class QueryRun:
    """질의 하나 실행 결과 — chunk_id 순서만(본문 없음). grades = 채운 칸마다 정답 등급(없으면 0)."""

    id: str
    split: str
    typology: str
    expect_empty: bool
    first: list[str]  # 지금 경로(빈칸 채우기 끔) 결과
    on: list[str]  # 빈칸 채우기 켬 결과
    grades: list[int]


def verdict(runs: list[QueryRun]) -> dict[str, Any]:
    for run in runs:  # 정답 없는 질의는 등급 없음(채운 칸이 생기면 ② 에서 떨어짐)
        if not run.expect_empty and len(run.grades) != max(len(run.on) - len(run.first), 0):
            raise ValueError(f"grades must match filled slots: {run.id}")
    holdout = [g for run in runs if run.split == "holdout" and not run.expect_empty for g in run.grades]
    correct = sum(1 for g in holdout if g >= ANSWER_GRADE_MIN)
    ratio = correct / len(holdout) if holdout else None
    empty_ok = all(run.on == [] for run in runs if run.expect_empty)
    first_ok = all(run.on[: len(run.first)] == run.first for run in runs)
    judged = len(holdout) >= VERDICT_MIN_SLOTS
    met = judged and ratio is not None and ratio >= VERDICT_RATIO_MIN and empty_ok and first_ok
    return {
        "filled_slots": len(holdout),
        "correct_slots": correct,
        "ratio": ratio,
        "empty_ok": empty_ok,
        "first_ok": first_ok,
        "judged": judged,
        "met": met,
        "criteria": {
            "ratio_min": VERDICT_RATIO_MIN,
            "min_slots": VERDICT_MIN_SLOTS,
            "grade_min": ANSWER_GRADE_MIN,
        },
    }


def expand_answers(draft: dict[str, Any], queries: list[dict[str, Any]]) -> dict[str, Any]:
    """(유형 × 청크) 초벌 → 질의별 정답(확인 전). 정답 없는 질의는 빠짐. 확인 칸은 비움 — 사람이 채움."""
    entries = [
        {
            "query_id": q["id"],
            "answers": [dict(a) for a in draft["by_typology"].get(q["typology"], [])],
            "draft": f"llm:{draft['prompt_version']}",
            "checked_by": None,
            "checked_at": None,
        }
        for q in queries
        if not q["expect_empty"]
    ]
    return {"_doc": "SCRUM-275 정답 — 위치(doc_id·page·pos)·chunk_id·grade 만, 원문 0. 확인자가 고치고 checked_by·checked_at 을 채움.",
            "queries": entries}  # fmt: skip


def unchecked(answers: dict[str, Any]) -> list[str]:
    return [e["query_id"] for e in answers["queries"] if not e.get("checked_by") or not e.get("checked_at")]


def grade_lookup(answers: dict[str, Any]) -> dict[str, dict[str, int]]:
    """질의 → {chunk_id: grade}. 표에 없는 청크는 0(오답)으로 셈."""
    return {e["query_id"]: {a["chunk_id"]: int(a["grade"]) for a in e["answers"]} for e in answers["queries"]}
