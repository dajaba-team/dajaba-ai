"""SCRUM-306 ★B-4 새 3문서 행 — 합의 태그(CYCLE·SG·GS) 대 305 확인 등급·305 LLM 초벌 등급 비교표 (03 5절).

무태그 청크는 305 확인 범위(후보 쪽) 밖이라 확인 등급은 보통 "확인 안 함". 출력은 수만(chunk_id·본문 0).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from tools.rag2_sample import ROOT

GRADES_305 = ROOT / "tests/str/rag_eval_corpus/answers_corpus.json"
DRAFT_305 = ROOT / "tests/str/rag_eval_corpus/answer_draft_corpus.json"
SHEET_TO_305 = {"CYCLE": "CYCLE", "SG": "SCATTER_GATHER", "GS": "GATHER_SCATTER"}
GRADE_MIN = 1
UNCHECKED = "확인 안 함"
NO_DRAFT = "초벌 없음"


def _bucket(grade: int | None, missing: str) -> str:
    return missing if grade is None else ("≥1" if grade >= GRADE_MIN else "0")


def _grades(graded: Mapping[str, list[dict]]) -> dict[tuple[str, str], int]:
    return {(t, r["chunk_id"]): int(r["grade"]) for t, rows in graded.items() for r in rows}


def compare(agreed: Mapping[str, frozenset[str]], confirmed: Mapping[str, list[dict]],
            draft: Mapping[str, list[dict]]) -> dict[str, dict[str, dict[str, int]]]:  # fmt: skip
    """유형마다 {"확인": {"붙임/≥1": n, ...}, "초벌": {...}} — 키 = 합의(붙임·안 붙임)/305 등급 칸."""
    conf, drf = _grades(confirmed), _grades(draft)
    out = {}
    for sheet_tag, typ in SHEET_TO_305.items():
        c_conf: Counter[str] = Counter()
        c_draft: Counter[str] = Counter()
        for cid, tags in agreed.items():
            side = "붙임" if sheet_tag in tags else "안 붙임"
            c_conf[f"{side}/{_bucket(conf.get((typ, cid)), UNCHECKED)}"] += 1
            c_draft[f"{side}/{_bucket(drf.get((typ, cid)), NO_DRAFT)}"] += 1
        out[sheet_tag] = {"확인": dict(sorted(c_conf.items())), "초벌": dict(sorted(c_draft.items()))}
    return out


def load_305(grades: Path = GRADES_305, draft: Path = DRAFT_305) -> tuple[dict, dict]:
    return (json.loads(grades.read_text(encoding="utf-8"))["grades"],
            json.loads(draft.read_text(encoding="utf-8"))["graded"])  # fmt: skip
