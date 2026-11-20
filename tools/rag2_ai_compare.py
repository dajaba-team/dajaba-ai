"""SCRUM-306 AI 보조 후보(`02`) 대 사람 합의 — 유형별 2×2 · κ · 놓친 수·잘못 붙인 수 (`03_sampling.md` 5절).

합의 = 정답. `02` 에 있는 행만(새 3문서 행은 AI 후보 없음 — 한계). `rag2_consensus` 가 불러 씀.
"""

from __future__ import annotations

import csv
from pathlib import Path

from tools.rag2_agreement import TAG_SEP, TYPES, kappa
from tools.rag2_sample import CANDIDATE_COL, REVIEW_CSV


def ai_candidates(path: Path = REVIEW_CSV) -> dict[str, frozenset[str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return {
            r["chunk_id"]: frozenset(t for t in r[CANDIDATE_COL].split(TAG_SEP) if t)
            for r in csv.DictReader(f)
        }


def ai_vs_consensus(agreed: dict[str, frozenset[str]], ai: dict[str, frozenset[str]]) -> dict[str, dict]:
    """합의 = 정답. 유형별 + 후보 유무 2×2 · κ · 놓친 수(fn) · 잘못 붙인 수(fp). `02` 에 있는 행만(새 3문서 행은 AI 후보 없음)."""
    ids = [c for c in agreed if c in ai]
    out = {}
    for typ in (*TYPES, None):
        truth = [bool(agreed[c]) if typ is None else typ in agreed[c] for c in ids]
        guess = [bool(ai[c]) if typ is None else typ in ai[c] for c in ids]
        tp = sum(t and g for t, g in zip(truth, guess, strict=True))
        fp, fn = sum(guess) - tp, sum(truth) - tp
        p_o, _, k = kappa(truth, guess)
        out[typ or "후보유무"] = {"tp": tp, "fp": fp, "fn": fn, "tn": len(ids) - tp - fp - fn,
                                 "missed": fn, "wrong": fp, "p_o": p_o, "kappa": k}  # fmt: skip
    return out
