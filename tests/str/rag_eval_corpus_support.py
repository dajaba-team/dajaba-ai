"""SCRUM-304 코퍼스 확장 판정 (docs/str/10 "코퍼스 확장 판정 (holdout_v2)", 09 2026-11-19). 질의 읽기 · 판정 · 상수.

판정 숫자는 결과를 보기 전에 09·10 에 커밋된 값 — 여기서 바꾸지 않는다. 275 `rag_eval_v2_support.verdict` 와 별개.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aml_ai.str.domain.rag_queries import build_query
from tests.str.rag_eval_corpus_guard import (
    EMPTY_CANDIDATES,
    JUDGED_TYPOLOGIES,
    FanCase,
    Manifest,
    PreRun,
    Prior,
    Run,
    check_inputs,
    check_snapshots,
)
from tests.str.rag_eval_v2_support import build_facts

CORPUS_EVAL_DIR = Path(__file__).parent / "rag_eval_corpus"
HIT_RATIO = (3, 4)  # ① ⌈0.75 × 질의 수⌉ — 정수로 계산
MIN_QUERIES = 6  # 같은 문자열은 하나로 센 질의 수가 이보다 적으면 판정 안 함
MIN_TAGGED_CHUNKS = 10  # 태그된 청크가 이보다 적으면 판정 안 함
GRADE_MIN = 1  # 정답 = 확인자 등급 ≥ 1
TOP_K_EVAL = 3
ADOPT_MIN_PASSED = 2  # ① 세 유형 중 통과 수가 이 이상이면 채택
FAN_BASELINE_HIT = 1.0  # ③ 확장 전 D07~D10 hit@3
CALIBRATION_ROWS = 25
CALIBRATION_MATCH_MIN = 20  # 기준 맞추기 "1 이상인가" 일치 행 수 하한
UNRELATED_NOTE = "참고 — 유형 없으면 [] 경로 확인용, 컷오프 연구는 SCRUM-308"


def load_queries() -> list[dict[str, Any]]:
    return json.loads((CORPUS_EVAL_DIR / "queries_holdout.json").read_text(encoding="utf-8"))["queries"]


def query_text(query: dict[str, Any]) -> str:
    """질의 문자열은 파일에 적지 않고 base + overrides 로 다시 만듦."""
    return build_query(build_facts(query))


def query_manifest() -> Manifest:
    """고정 질의 목록 (id, 유형, 문자열) — 305 실행 결과를 이것과 대조(빠짐·중복·목록 밖 거절)."""
    return [(q["id"], q["typology"], query_text(q)) for q in load_queries()]


def hits_needed(n: int) -> int:
    num, den = HIT_RATIO
    return -(-num * n // den)


def _is_hit(top: list[str], grade_of: dict[str, int]) -> bool:
    return any(grade_of.get(c, 0) >= GRADE_MIN for c in top[:TOP_K_EVAL])


def _typology(typ: str, runs: list[Run], pre: PreRun, grades: dict[tuple[str, str], int], pinned: str | None) -> dict:  # fmt: skip
    unique = {
        r.text: r for r in reversed([r for r in runs if r.typology == typ])
    }  # 같은 문자열 = 먼저 나온 것
    grade_of = {c: g for (t, c), g in grades.items() if t == typ}
    hits = sum(_is_hit(r.top, grade_of) for r in unique.values())
    out = {"queries": len(unique), "hits": hits, "need": hits_needed(len(unique)),
           "tagged": pre.tagged.get(typ, 0), "checked": pre.checked.get(typ, False)}  # fmt: skip
    if pinned == "fail":
        return {**out, "status": "fail", "reason": "pinned"}  # 미달은 나중에 판정 안 함으로 못 바꿈
    for reason, short in (("queries", out["queries"] < MIN_QUERIES),
                          ("tagged", out["tagged"] < MIN_TAGGED_CHUNKS), ("unchecked", not out["checked"])):  # fmt: skip
        if short:
            return {**out, "status": "not_judged", "reason": reason}
    return {**out, "status": "pass" if hits >= out["need"] else "fail", "reason": None}


def _empty(runs: list[Run], pre: PreRun) -> dict:
    judged = [t for t in EMPTY_CANDIDATES if pre.tagged.get(t, 0) == 0]
    excluded = {t: pre.tagged[t] for t in EMPTY_CANDIDATES if t not in judged}
    failures = [r.id for r in runs if r.typology in judged and r.top]
    return {"judged": judged, "excluded": excluded, "failures": failures, "ok": not failures}


def _fan(cases: list[FanCase]) -> dict:
    before = sum(_is_hit(c.before, c.grades) for c in cases) / len(cases)
    after = sum(_is_hit(c.after, c.grades) for c in cases) / len(cases)
    displaced = sum(
        1 for c in cases for cid in c.before[:TOP_K_EVAL]
        if c.grades.get(cid, 0) >= GRADE_MIN and cid not in c.after[:TOP_K_EVAL]
    )  # fmt: skip
    return {"hit_before": before, "hit_after": after, "displaced": displaced, "ok": after >= FAN_BASELINE_HIT}


def verdict(
    runs: list[Run],
    pre: PreRun,
    grades: dict[tuple[str, str], int],
    fan: list[FanCase],
    *,
    manifest: Manifest,
    pre_sha256: str,
    prior: Prior | None,
    prior_sha256: str | None,
) -> dict[str, Any]:
    """`manifest` = 고정 질의 목록 · `pre_sha256` = 예약 때 적은 실행 전 고정값 해시 · `prior` = 원장에 적힌 이전
    판정 기록(첫 판정은 None 명시)과 그 해시 — 다르면 판정 전에 거절. 미달 고정은 `prior` 에서만 계산."""
    check_snapshots(pre, pre_sha256, prior, prior_sha256)
    check_inputs(runs, fan, manifest=manifest)
    pinned = dict(prior.statuses) if prior else {}
    typology = {t: _typology(t, runs, pre, grades, pinned.get(t)) for t in JUDGED_TYPOLOGIES}
    empty, fan_out = _empty(runs, pre), _fan(fan)
    passed = sum(1 for v in typology.values() if v["status"] == "pass")
    adopt = empty["ok"] and fan_out["ok"] and passed >= ADOPT_MIN_PASSED
    return {
        "typology": typology,
        "empty": empty,
        "unrelated": [{"id": r.id, "returned": len(r.top)} for r in runs if r.typology is None],
        "fan": fan_out,
        "passed": passed,
        "conclusion": "adopt" if adopt else "restore",
        "criteria": {
            "hit_ratio": f"{HIT_RATIO[0]}/{HIT_RATIO[1]}",
            "min_queries": MIN_QUERIES,
            "min_tagged_chunks": MIN_TAGGED_CHUNKS,
            "grade_min": GRADE_MIN,
            "top_k": TOP_K_EVAL,
            "adopt_min_passed": ADOPT_MIN_PASSED,
            "fan_baseline_hit": FAN_BASELINE_HIT,
        },  # fmt: skip
    }


def calibration_agrees(reference: dict[tuple[str, str], int], checker: dict[tuple[str, str], int]) -> dict:
    """기준 맞추기 — 준혁 등급과 확인자 등급의 "1 이상인가" 일치 행 수. 행이 다르면 거절."""
    if set(reference) != set(checker) or len(reference) != CALIBRATION_ROWS:
        raise ValueError("calibration rows must be the same 25 rows")
    matches = sum((reference[k] >= GRADE_MIN) == (checker[k] >= GRADE_MIN) for k in reference)
    return {"rows": len(reference), "matches": matches, "same": matches >= CALIBRATION_MATCH_MIN,
            "match_min": CALIBRATION_MATCH_MIN}  # fmt: skip
