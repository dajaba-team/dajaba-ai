"""SCRUM-308 ③ 청크 맥락 — 두 표 재임베딩 대조를 한 쌍으로 (추가 검토 3, docs/str/10 "청크 맥락").

청크마다 다시 만든 본문 벡터 B'(지금 표 문장)와 기대 머리말 벡터 H'(새 표 문장)로:
지금 표 C 는 cos(C,B') ≥ 0.99 이고 cos(C,B') > cos(C,H') · 새 표 N 은 cos(N,H') ≥ 0.99 이고 cos(N,H') > cos(N,B')
(유한값만) — 머리말 없이 임베딩한 새 표 행(cos 0.99 를 넘어도)을 가름. B'·H' 가 사실상 같은 청크(cos ≥ 0.999,
본문이 거의 없는 경우)는 가까운 쪽 비교 대신 수만 기록. 외부 호출 = 두 표 문장 각 1벌(722 + 722) — 새 호출 0.
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.infrastructure.embedding_client import HttpEmbeddingClient
from tests.str.rag_eval_v3_rerank_recheck import cosine, passes

INDISTINCT_COS = 0.999  # B'·H' 가 이 이상이면 머리말이 임베딩을 거의 안 바꾼 청크 — 가까운 쪽 비교 안 함


def same_vector_rows(session: Session) -> int:
    """두 표 같은 chunk_id 의 저장 벡터가 완전히 같은 행 수(머리말 없는 벡터 복사) — 0 이어야."""
    return (
        session.execute(
            text(
                "SELECT count(*) FROM ai.reference_chunks a JOIN ai.reference_chunks_ctx b USING (chunk_id) "
                "WHERE a.embedding = b.embedding"
            )
        ).scalar()
        or 0
    )


def _side(
    stored: list[float], own: list[float], other: list[float], check_closer: bool
) -> tuple[float, bool, bool]:
    near, far = cosine(stored, own), cosine(stored, other)
    return near, not passes(near), check_closer and not (math.isfinite(near) and near > far)


def paired_recheck(cur: dict, ctx: dict, settings: Settings) -> dict[str, Any]:
    """cur·ctx = chunk_id → (임베딩 문장, 저장 벡터). 두 표 같은 id 여야. → 표별 {chunks, min_cos, below, closer_violations}."""
    if set(cur) != set(ctx):
        raise ValueError("두 표 재검사 대상이 다름")
    ids = sorted(cur)
    client = HttpEmbeddingClient(settings)
    body = dict(zip(ids, client.embed([cur[c][0] for c in ids]), strict=True)) if ids else {}
    head = dict(zip(ids, client.embed([ctx[c][0] for c in ids]), strict=True)) if ids else {}
    out: dict[str, Any] = {
        k: {"chunks": len(ids), "cos": [], "below": 0, "closer_violations": 0} for k in ("current", "ctx")
    }
    indistinct = 0
    for c in ids:
        apart = not cosine(body[c], head[c]) >= INDISTINCT_COS  # NaN 이면 비교함(→ 위반)
        indistinct += not apart
        for name, stored, own, other in (
            ("current", cur[c][1], body[c], head[c]),
            ("ctx", ctx[c][1], head[c], body[c]),
        ):
            cos, below, closer = _side(stored, own, other, apart)
            side = out[name]
            side["cos"].append(cos)
            side["below"] += below
            side["closer_violations"] += closer
    for side in out.values():
        finite = [x for x in side.pop("cos") if math.isfinite(x)]
        side["min_cos"] = round(min(finite), 6) if finite else None
    return {**out, "indistinct": indistinct}


def paired_problem(summary: dict[str, Any]) -> str | None:
    for name in ("current", "ctx"):
        s = summary[name]
        if not s["chunks"]:
            return f"{name} 표 재임베딩 대조 대상 0 청크"
        if s["below"] or s["closer_violations"]:
            return f"{name} 표 재임베딩 대조 실패 — cos < 0.99 {s['below']} · 다른 문장 쪽이 더 가까움 {s['closer_violations']}"
    return None
