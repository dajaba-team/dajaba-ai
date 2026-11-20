"""SCRUM-305 ③ D07~D10 입력 (docs/str/10 "305 실행 기록") — 275 개발용 파일 읽기만, DB·검색 0.

확장 전 top-3 = 275 `result_dev.json` 의 원래 검색(`first`) · 등급 = 준혁(`answers_dev.json`) · 질의 facts = 275 개발용 질의.
"""

from __future__ import annotations

import json

from tests.str.rag_eval_corpus_guard import FAN_CASE_IDS, FanCase
from tests.str.rag_eval_v2_support import EVAL_DIR as V2_DIR
from tests.str.rag_eval_v2_support import build_facts, grade_lookup
from tests.str.rag_eval_v2_support import load_queries as load_v2


def dev_fan_grades() -> dict[str, dict[str, int]]:
    return grade_lookup(json.loads((V2_DIR / "answers_dev.json").read_text(encoding="utf-8")))


def dev_fan_facts() -> list:
    dev = {q["id"]: q for q in load_v2("dev")}
    return [build_facts(dev[i]) for i in FAN_CASE_IDS]


def fan_cases(after: list[list[str]]) -> list[FanCase]:
    runs = json.loads((V2_DIR / "result_dev.json").read_text(encoding="utf-8"))["runs"]
    before = {r["id"]: r["first"] for r in runs}
    grades = dev_fan_grades()
    return [FanCase(i, before[i], a, grades.get(i, {})) for i, a in zip(FAN_CASE_IDS, after, strict=True)]
