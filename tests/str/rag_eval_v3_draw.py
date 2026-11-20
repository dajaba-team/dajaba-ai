"""SCRUM-306 개발용 평가 세트 v3 — 질의 34 기계 추출 (docs/str/10 "2차로 넘기는 것" SCRUM-306 줄).

사람이 고르지 않음: 시드 306 으로 다시 뽑으면 리포 파일과 같아야 함(테스트). 기존 275 dev·보류용·holdout_v2
질의와 문자열이 같으면 건너뜀. 검색·DB·LLM 0.
"""

from __future__ import annotations

import itertools
import json
import random
from pathlib import Path
from typing import Any

from aml_ai.str.domain.rag_queries import build_query
from tests.str.rag_eval_corpus_draw import INDUSTRIES, SIGNALS
from tests.str.rag_eval_corpus_support import load_queries as load_holdout_v2
from tests.str.rag_eval_v2_support import build_facts
from tests.str.rag_eval_v2_support import load_queries as load_v2

V3_DIR = Path(__file__).parent / "rag_eval_v3"
QUERIES_FILE = V3_DIR / "queries_dev.json"
QUERY_SEED = 306
SPLIT = "dev_v3"
UNRELATED_BASE = "facts_fan_in_b.json"
UNRELATED_INDUSTRIES = ["RETAIL", "MANUFACTURING", "RESTAURANT", "WHOLESALE", "TRADING", None]
# (유형, id 앞자리, 개수, base 들(번갈아), uses) — 이 순서로 같은 난수열을 이어 씀. 유형 None = 무관한 질의
PLAN = [
    ("FAN_IN", "FI", 6, ["facts_fan_in.json", "facts_fan_in_b.json", "facts_multi_currency.json"], ["hit"]),
    ("FAN_OUT", "FO", 6, ["facts_fan_out.json", "facts_multi_currency.json"], ["hit"]),
    ("CYCLE", "CY", 6, ["facts_cycle_nopaths.json", "facts_multi_currency.json"], ["hit"]),
    ("SCATTER_GATHER", "SG", 6, ["facts_scatter_gather.json"], ["hit"]),
    ("GATHER_SCATTER", "GS", 6, ["facts_scatter_gather.json"], ["hit"]),
    ("FX_RELAY", "FX", 2, ["facts_multi_currency.json"], ["empty"]),
    (None, "NR", 2, [UNRELATED_BASE], ["reference"]),
]
QUERIES_DOC = (
    "SCRUM-306 개발용 평가 세트 v3 질의 — 시드 306 기계 추출, 정답 없음(answer_candidates.json 따로)."
)


def existing_texts() -> set[str]:
    """건너뛸 기존 질의 문자열 — 275 dev·보류용 + 304 holdout_v2."""
    queries = [*load_v2("dev"), *load_v2("holdout"), *load_holdout_v2()]
    return {build_query(build_facts(q)) for q in queries}


def _combos(typ: str | None) -> list[tuple[list[str], str | None]]:
    if typ is None:
        return [([], ind) for ind in UNRELATED_INDUSTRIES]
    return [(list(s), ind) for k in (1, 2) for s in itertools.permutations(SIGNALS, k) for ind in INDUSTRIES]


def draw_queries(taken: set[str]) -> list[dict[str, Any]]:
    rng = random.Random(QUERY_SEED)
    seen = set(taken)
    out: list[dict[str, Any]] = []
    for typ, prefix, n, bases, uses in PLAN:
        combos = _combos(typ)
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
        if len(picked) < n:
            raise ValueError(f"{prefix}: 새 질의 문자열이 모자람")
        out += picked
    return out


def load_queries() -> list[dict[str, Any]]:
    return json.loads(QUERIES_FILE.read_text(encoding="utf-8"))["queries"]


def main() -> None:
    V3_DIR.mkdir(exist_ok=True)
    doc = {"_doc": QUERIES_DOC, "queries": draw_queries(existing_texts())}
    QUERIES_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(doc['queries'])} queries")


if __name__ == "__main__":
    main()
