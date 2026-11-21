"""SCRUM-307 하이브리드·다중 질의 판정 — 순수 계산 (docs/str/10 "하이브리드·다중 질의 판정", 09 2026-11-21).

조건 9 · 지표(hit@3·recall@10) · 켜는 규칙 ①②③. 숫자는 결과를 보기 전에 커밋한 10_rag 절 그대로 — 여기서 바꾸지 않는다.
DB·임베딩·ES·git 0. 청크는 chunk_id 로만 다루고 원문·검색어 문장은 받지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

V3_DIR = Path(__file__).parent / "rag_eval_v3"
RESULT_FILE = V3_DIR / "result_307.json"
DRY_RESULT_FILE = V3_DIR / "result_307_dry.json"
POSITIONS_FILE = V3_DIR / "positions_722.json"
CANDIDATES_FILE = V3_DIR / "answer_candidates.json"
QUERIES_FILE = V3_DIR / "queries_dev.json"
CRITERIA_HEADING = "## 하이브리드·다중 질의 판정 (SCRUM-307"
CRITERIA_09_PREFIX = "| 2026-11-21 (SCRUM-307 하이브리드·다중 질의 판정 기준"
ES_INDEX = "ai_reference_chunks_v2"

KIND_COMBOS: tuple[tuple[str, ...], ...] = (("a",), ("a", "c"), ("a", "b", "c"))
BASE_KINDS = ("a",)
JUDGED_TYPES = ("FAN_IN", "FAN_OUT", "CYCLE", "GATHER_SCATTER")  # SG 는 표에만(정답 2청크 — 한계 ②)
TABLE_TYPES = (*JUDGED_TYPES, "SCATTER_GATHER")
COMBO_GAIN_MIN = 0.10  # ① 평균 recall@10 오름 하한
HIT_DROP_MAX = 0.05  # ① 유형별 hit@3 하락 상한(초과면 탈락 — 질의 6개라 hit 하나 = 0.167)
TIE_MARGIN = 0.02  # ① 두 조합 오른 폭 차이가 이 안이면 검색어 적은 쪽
KEYWORD_GAIN_MIN = 0.05  # ② 키워드 켬 − 끔 평균 recall@10 하한
DIGITS = 3  # 비교는 소수 3자리 반올림 뒤
GRADE_MIN = 1
TOP_HIT = 3
TOP_RECALL = 10
FORBIDDEN_KEYS = frozenset({"text", "query", "sentence", "body", "snippet", "content", "text_en", "text_ko"})


@dataclass(frozen=True)
class Condition:
    filtered: bool
    kinds: tuple[str, ...]
    keyword: bool

    @property
    def name(self) -> str:
        return f"{'on' if self.filtered else 'off'}_{''.join(self.kinds)}_kw{int(self.keyword)}"


def conditions() -> list[Condition]:
    """필터 끔 6(조합 × 키워드 끔·켬) + 필터 켬 3(키워드 끔). 필터 켬 + 키워드는 해당 없음."""
    off = [Condition(False, kinds, kw) for kinds in KIND_COMBOS for kw in (False, True)]
    return off + [Condition(True, kinds, False) for kinds in KIND_COMBOS]


def answer_sets(candidates: dict[str, Any], *, filtered: bool) -> dict[str, set[str]]:
    """유형 → 정답 chunk_id(등급 ≥ 1). 필터 켬은 `db_tagged=true` 만."""
    return {
        typ: {
            r["chunk_id"] for r in rows if (r["grade"] or 0) >= GRADE_MIN and (r["db_tagged"] or not filtered)
        }
        for typ, rows in candidates["candidates"].items()
    }


def unconfirmed(candidates: dict[str, Any]) -> str | None:
    """v3 정답 확인이 안 끝났으면 이유, 끝났으면 None."""
    if candidates.get("consensus_pending") is not False:
        return "consensus_pending 이 false 가 아님"
    for key in ("fan_checked_by", "fan_checked_at", "consensus_checked_by", "consensus_checked_at"):
        if not candidates.get(key):
            return f"{key} 빈 칸"
    blank = sum(r.get("grade") is None for rows in candidates["candidates"].values() for r in rows)
    return f"등급 빈 칸 {blank}" if blank else None


def _r(x: float) -> float:
    return round(x, DIGITS)


def metrics(records: list[dict[str, Any]], answers: dict[str, set[str]]) -> dict[str, Any]:
    """records = [{typology, top10: [chunk_id, ...]}] → 유형별 {n, hit3, recall10} + 4유형 평균. 정답 0 질의는 뺌."""
    per: dict[str, dict[str, list[float]]] = {}
    for rec in records:
        expected = answers.get(rec["typology"] or "", set())
        if not expected:
            continue
        top = rec["top10"]
        row = per.setdefault(rec["typology"], {"hit3": [], "recall10": []})
        row["hit3"].append(1.0 if set(top[:TOP_HIT]) & expected else 0.0)
        row["recall10"].append(len(set(top[:TOP_RECALL]) & expected) / len(expected))
    raw = {t: {m: sum(v[m]) / len(v[m]) for m in v} for t, v in per.items()}
    judged = [
        raw[t] for t in JUDGED_TYPES if t in raw
    ]  # 평균은 반올림 전 값으로(추가 검토 1) — 3자리는 맨 끝에만
    mean = {m: _r(sum(t[m] for t in judged) / len(judged)) if judged else None for m in ("hit3", "recall10")}
    types = {t: {"n": len(per[t]["hit3"]), **{m: _r(x) for m, x in v.items()}} for t, v in raw.items()}
    return {"types": types, "mean": mean}


def _hit_drop_ok(base: dict[str, Any], other: dict[str, Any], limit: float) -> bool:
    return all(_r(base["types"][t]["hit3"] - other["types"][t]["hit3"]) <= limit for t in JUDGED_TYPES)


def choose_combo(by_kinds: dict[tuple[str, ...], dict[str, Any]]) -> dict[str, Any]:
    """규칙 ① — 필터 끔·키워드 끔 지표(조합별) → 고른 조합. 못 넘으면 {a}."""
    base = by_kinds[BASE_KINDS]
    passed = []
    for kinds in KIND_COMBOS[1:]:
        gain = _r(by_kinds[kinds]["mean"]["recall10"] - base["mean"]["recall10"])
        if gain >= COMBO_GAIN_MIN and _hit_drop_ok(base, by_kinds[kinds], HIT_DROP_MAX):
            passed.append((kinds, gain))
    if not passed:
        return {"kinds": list(BASE_KINDS), "passed": []}
    best = max(passed, key=lambda p: p[1])
    fewer = min(passed, key=lambda p: len(p[0]))
    chosen = fewer if _r(best[1] - fewer[1]) <= TIE_MARGIN else best
    return {"kinds": list(chosen[0]), "passed": [{"kinds": list(k), "gain": g} for k, g in passed]}


def choose_keyword(off: dict[str, Any], on: dict[str, Any]) -> dict[str, Any]:
    """규칙 ② — 고른 조합에서만. 켬 − 끔 평균 recall@10 ≥ 0.05 면 켬."""
    gain = _r(on["mean"]["recall10"] - off["mean"]["recall10"])
    return {"keyword": gain >= KEYWORD_GAIN_MIN, "gain": gain}


def filter_on_usable(by_kinds: dict[tuple[str, ...], dict[str, Any]]) -> list[list[str]]:
    """규칙 ③ — 필터 켬 지표(조합별). {a} 보다 hit@3 이 한 유형이라도 낮지 않은 조합만."""
    base = by_kinds[BASE_KINDS]
    return [list(k) for k in KIND_COMBOS[1:] if _hit_drop_ok(base, by_kinds[k], 0.0)]


def verdict(by_condition: dict[Condition, dict[str, Any]]) -> dict[str, Any]:
    off = {c.kinds: m for c, m in by_condition.items() if not c.filtered and not c.keyword}
    combo = choose_combo(off)
    chosen = tuple(combo["kinds"])
    kw = {c.keyword: m for c, m in by_condition.items() if not c.filtered and c.kinds == chosen}
    on = {c.kinds: m for c, m in by_condition.items() if c.filtered}
    return {
        "combo": combo,
        "keyword": choose_keyword(kw[False], kw[True]),
        "filter_on_usable": filter_on_usable(on),
    }


def latency(ms: list[float]) -> dict[str, Any]:
    return {
        "n": len(ms),
        "p50": round(median(ms), 1) if ms else None,
        "max": round(max(ms), 1) if ms else None,
    }


def criteria_section(md: str) -> str | None:
    """10_rag 의 307 절(제목부터 다음 `## ` 앞까지). 없으면 None."""
    start = md.find(CRITERIA_HEADING)
    if start < 0:
        return None
    end = md.find("\n## ", start + 1)
    return md[start : end if end >= 0 else len(md)]


def criteria_line(md: str) -> str | None:
    return next((line for line in md.splitlines() if line.startswith(CRITERIA_09_PREFIX)), None)


def forbidden_keys(doc: Any, path: str = "") -> list[str]:
    """결과 안에 본문·검색어 문장이 들어갈 키가 있으면 그 경로들."""
    found: list[str] = []
    if isinstance(doc, dict):
        for key, value in doc.items():
            if key in FORBIDDEN_KEYS:
                found.append(f"{path}/{key}")
            found += forbidden_keys(value, f"{path}/{key}")
    elif isinstance(doc, list):
        for i, value in enumerate(doc):
            found += forbidden_keys(value, f"{path}[{i}]")
    return found
