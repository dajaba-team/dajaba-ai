"""SCRUM-308 ③ 청크 맥락 판정 — 순수 계산 (docs/str/10 "청크 맥락·리랭커·컷오프 판정" ③, 기준 커밋 87aef09).

같은 실행·같은 질의 벡터로 지금 표와 새 표를 초안 경로(필터 켬 {a} · 후보 10)로 비교. 정답 = 등급 ≥ 1 · `db_tagged=true`.
통과 = 4유형 평균 precision@3(새 − 지금) ≥ +0.10 · 4유형 각각 hit@3·recall@10 하락 없음 · 정답 없는 질의(필터 켬) 0건.
SG·필터 끔은 표에만. 숫자는 결과 보기 전 커밋한 기준 그대로 — 여기서 바꾸지 않는다. DB·임베딩 0.
"""

from __future__ import annotations

from typing import Any

from tests.str import rag_eval_v3_hybrid_support as hs
from tests.str import rag_eval_v3_rerank_support as rs
from tests.str.rag_eval_v3_hybrid_support import JUDGED_TYPES, V3_DIR

RESULT_FILE = V3_DIR / "result_308_ctx.json"
DRY_RESULT_FILE = V3_DIR / "result_308_ctx_dry.json"
PRECISION_GAIN_MIN = 0.10  # ③ 4유형 평균 precision@3 오름 하한
_r = rs._r  # noqa: SLF001 — 308-2 와 같은 반올림


def metrics(tops: dict[str, list[str]], queries: list[dict], answers: dict[str, set[str]]) -> dict[str, Any]:
    """질의 id → 후보 chunk_id(순서대로) → 유형별 {n, precision3, hit3, recall10} + 4유형 평균 precision@3."""
    p = rs.metrics([{"typology": q["typology"], "top": tops[q["id"]]} for q in queries], answers)
    r = hs.metrics([{"typology": q["typology"], "top10": tops[q["id"]]} for q in queries], answers)
    types = {t: {**v, "recall10": r["types"][t]["recall10"]} for t, v in p["types"].items()}
    return {"types": types, "mean_precision3": p["mean_precision3"], "mean_recall10": r["mean"]["recall10"]}


def no_answer_leaks(
    tops: dict[str, list[str]], queries: list[dict], answers: dict[str, set[str]]
) -> list[str]:
    return [q["id"] for q in queries if not answers.get(q["typology"] or "") and tops[q["id"]]]


def verdict(cur: dict[str, Any], ctx: dict[str, Any], leaks: list[str], *, dry: bool) -> dict[str, Any]:
    gain = _r(ctx["mean_precision3"] - cur["mean_precision3"])
    hit_drops = [t for t in JUDGED_TYPES if _r(cur["types"][t]["hit3"] - ctx["types"][t]["hit3"]) > 0]
    recall_drops = [
        t for t in JUDGED_TYPES if _r(cur["types"][t]["recall10"] - ctx["types"][t]["recall10"]) > 0
    ]
    checks = {
        "precision_gain": gain >= PRECISION_GAIN_MIN,
        "no_hit_drop": not hit_drops,
        "no_recall10_drop": not recall_drops,
        "no_answer_empty": not leaks,
    }
    out = {"gain": gain, "hit_drops": hit_drops, "recall10_drops": recall_drops, "no_answer_leaks": leaks,
           "checks": checks, "judged": True, "adopt": all(checks.values())}  # fmt: skip
    if dry:
        return {**out, "judged": False, "adopt": False, "reason": "dry — 가짜 벡터"}
    return out


def record(q: dict, got: dict, positions: dict) -> dict:
    def rows(refs: list) -> list[dict]:
        return [{"rank": i, "chunk_id": r.chunk_id, **{k: positions[r.chunk_id][k] for k in ("doc_id", "page", "pos")},
                 "cosine": round(r.score, 6)} for i, r in enumerate(refs, 1)]  # fmt: skip

    keys = ("current_on", "ctx_on", "current_off", "ctx_off")
    return {
        "id": q["id"],
        "typology": q["typology"],
        "uses": q["uses"],
        **{k: rows(got[k][q["id"]]) for k in keys},
    }
