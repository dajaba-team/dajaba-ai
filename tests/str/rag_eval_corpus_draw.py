"""SCRUM-304 기계 추출 — holdout_v2 질의 · 기준 맞추기 표본 (docs/str/10 "코퍼스 확장 판정 (holdout_v2)").

사람이 고르지 않음: 고정 시드로 다시 뽑으면 리포 파일과 같아야 함(테스트). 검색·DB·LLM 0.
"""

from __future__ import annotations

import itertools
import json
import random
from typing import Any

from aml_ai.str.domain.rag_queries import build_query
from tests.str.rag_eval_corpus_support import UNRELATED_NOTE
from tests.str.rag_eval_v2_support import EVAL_DIR, build_facts

QUERY_SEED = 304
SPLIT = "holdout_v2"
SIGNALS = [  # 275 질의에 나온 신호 6개
    "account_in_counterparties_24h",
    "cross_border_amount_24h",
    "distinct_recipients_24h",
    "distinct_senders_24h",
    "inflow_outflow_ratio_2h",
    "outflow_ratio_2h",
]
INDUSTRIES = ["RETAIL", "WHOLESALE", "TRADING", "RESTAURANT", None]  # None = 업종 없음
UNRELATED_INDUSTRIES = ["RETAIL", "MANUFACTURING"]
# (유형, id 앞자리, 개수, base 들(번갈아), uses) — 이 순서로 같은 난수열을 이어 씀
PLAN = [
    ("CYCLE", "CY", 8, ["facts_cycle_nopaths.json", "facts_multi_currency.json"], ["hit"]),
    ("SCATTER_GATHER", "SG", 8, ["facts_scatter_gather.json"], ["hit", "empty"]),
    ("GATHER_SCATTER", "GS", 8, ["facts_scatter_gather.json"], ["hit", "empty"]),
    ("FX_RELAY", "FX", 4, ["facts_multi_currency.json"], ["empty"]),
]

CALIBRATION_SEEDS = (304, 3042)  # 1차 · 2차(1차 미달 때만)
CALIBRATION_QUOTAS = {  # (유형, 준혁 등급) → 행 수, 합 25 · "1 이상" 15
    ("CYCLE", 1): 3, ("CYCLE", 0): 7,
    ("FAN_IN", 2): 4, ("FAN_IN", 1): 4, ("FAN_IN", 0): 2,
    ("FAN_OUT", 2): 2, ("FAN_OUT", 1): 2, ("FAN_OUT", 0): 1,
}  # fmt: skip
CALIBRATION_DOC = (
    "SCRUM-304 기준 맞추기 표본 — 위치·chunk_id·유형만. 2차는 1차 미달 때만(docs/str/10 코퍼스 확장 판정)."
)


def draw_queries(taken: set[str]) -> list[dict[str, Any]]:
    """`taken`(기존 30개 문자열)·이미 뽑은 것과 같은 문자열은 건너뛰고 유형마다 앞에서 N개 + 무관한 질의 2개."""
    rng = random.Random(QUERY_SEED)
    seen = set(taken)
    out: list[dict[str, Any]] = []
    for typ, prefix, n, bases, uses in PLAN:
        combos = [
            (list(s), ind) for k in (1, 2) for s in itertools.permutations(SIGNALS, k) for ind in INDUSTRIES
        ]
        rng.shuffle(combos)
        picked: list[dict[str, Any]] = []
        for signals, industry in combos:
            query = {"id": f"{prefix}{len(picked) + 1:02d}", "split": SPLIT, "typology": typ,
                     "base": bases[len(picked) % len(bases)],
                     "overrides": {"industry": industry, "model_signals": signals}, "uses": uses}  # fmt: skip
            text = build_query(build_facts(query))
            if text in seen:
                continue
            seen.add(text)
            picked.append(query)
            if len(picked) == n:
                break
        out += picked
    return out + [
        {"id": f"NR{i:02d}", "split": SPLIT, "typology": None, "base": "facts_fan_in_b.json",
         "overrides": {"industry": ind, "model_signals": []}, "uses": ["reference"], "note": UNRELATED_NOTE}
        for i, ind in enumerate(UNRELATED_INDUSTRIES, 1)
    ]  # fmt: skip


def calibration_population() -> list[dict[str, Any]]:
    """준혁 님이 확인한 행 — CYCLE 425 전부 + FAN_IN·FAN_OUT 의 LLM ≥ 1 행. grade = 준혁 등급(표에 없으면 0)."""
    draft = json.loads((EVAL_DIR / "answer_draft.json").read_text(encoding="utf-8"))["graded_by_typology"]
    answers = json.loads((EVAL_DIR / "answers_holdout.json").read_text(encoding="utf-8"))["queries"]
    queries = json.loads((EVAL_DIR / "queries_holdout.json").read_text(encoding="utf-8"))["queries"]
    typ_of = {q["id"]: q["typology"] for q in queries}
    human = {typ_of[e["query_id"]]: {a["chunk_id"]: int(a["grade"]) for a in e["answers"]} for e in answers}
    return [
        {"chunk_id": r["chunk_id"], "typology": typ, "doc_id": r["doc_id"], "page": r["page"], "pos": r["pos"],
         "grade": human[typ].get(r["chunk_id"], 0)}
        for typ in ("CYCLE", "FAN_IN", "FAN_OUT")
        for r in draft[typ]
        if typ == "CYCLE" or r["grade"] >= 1
    ]  # fmt: skip


def _round(
    population: list[dict[str, Any]], seed: int, exclude: set[tuple[str, str]]
) -> tuple[list[dict], int]:
    rng = random.Random(seed)
    picked: list[dict[str, Any]] = []
    reused = 0
    for (typ, grade), k in CALIBRATION_QUOTAS.items():
        pool = sorted((r for r in population if r["typology"] == typ and r["grade"] == grade), key=lambda r: r["chunk_id"])  # fmt: skip
        fresh = [r for r in pool if (typ, r["chunk_id"]) not in exclude]
        if len(fresh) >= k:
            picked += rng.sample(fresh, k)
        else:  # 모자란 층은 1차 행을 다시 씀
            picked += fresh + rng.sample([r for r in pool if r not in fresh], k - len(fresh))
            reused += k - len(fresh)
    return sorted(picked, key=lambda r: (r["chunk_id"], r["typology"])), reused


def draw_calibration(population: list[dict[str, Any]]) -> dict[str, Any]:
    """층 순서가 드러나지 않게 chunk_id 순으로 · 등급 칸 없이."""
    rounds: list[dict[str, Any]] = []
    exclude: set[tuple[str, str]] = set()
    for n, seed in enumerate(CALIBRATION_SEEDS, 1):
        rows, reused = _round(population, seed, exclude)
        exclude |= {(r["typology"], r["chunk_id"]) for r in rows}
        handoff = [
            {"row_id": f"R{n}-{i:02d}", "chunk_id": r["chunk_id"], "typology": r["typology"],
             "doc_id": r["doc_id"], "page": r["page"], "pos": r["pos"]}
            for i, r in enumerate(rows, 1)
        ]  # fmt: skip
        rounds.append({"seed": seed, "rows": handoff} | ({"reused_from_round1": reused} if n > 1 else {}))
    return {"_doc": CALIBRATION_DOC, "population": len(population), "rounds": rounds}
