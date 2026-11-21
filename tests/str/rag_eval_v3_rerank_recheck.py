"""SCRUM-308 ② 판정 전 코퍼스 재임베딩 대조 (추가 검토 4 — 판정 기준 87aef09 안 바꿈, 지표 계산 전 "입력 확인").

기존 코퍼스는 적재 당시 응답 모델을 확인하지 않았음 → 전체 재적재 대신, 평가 질의들의 유형 필터를 통과하는 **모든** 청크
(순위와 무관 — 손상된 벡터가 10위 밖으로 밀려도 대상, 검토 5)를 검증 경로(`HttpEmbeddingClient` — 응답 모델 = 질의 모델일
때만 벡터)로 다시 임베딩해 저장 벡터와 cos ≥ 0.99(유한값)일 때만 진행. 한 청크라도 아니면 리랭커 호출 전 중단(결과 파일 0).
0.99 는 같은 모델 재호출 흔들림 여유(307 CY03). cosine 은 정규화 후 내적(오버플로 회피), NaN·inf 는 실패로 셈.
저장 벡터·본문은 후보와 **같은 스냅샷**에서 읽고, 재임베딩(외부 호출)은 스냅샷을 닫은 뒤.
"""

from __future__ import annotations

import json
import math
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import EmbeddingModelMismatch
from aml_ai.shared.infrastructure.embedding_client import HttpEmbeddingClient
from aml_ai.str.domain.rag_queries import SearchQuery
from tests.str.rag_baseline_live_run import PreparedEmbedding, prepare

MIN_COS = 0.99


def filtered_rows(session: Session, typologies: list[str], model: str) -> dict[str, tuple[str, list[float]]]:
    """chunk_id → (본문, 저장 벡터) — 평가 질의 유형 중 하나라도 태그된 같은 모델 청크 전부. 같은 스냅샷 세션에서."""
    rows = session.execute(
        text(
            "SELECT chunk_id, text, embedding::text AS vec FROM ai.reference_chunks "
            "WHERE embedding_model = :model AND typologies && CAST(:tys AS text[])"
        ),
        {"model": model, "tys": typologies},
    ).all()
    return {r.chunk_id: (r.text, json.loads(r.vec)) for r in rows}


def _unit(v: list[float]) -> list[float]:
    scale = max((abs(x) for x in v), default=0.0)
    if not math.isfinite(scale) or scale == 0:
        return [math.nan] * len(v)
    w = [x / scale for x in v]
    norm = math.sqrt(math.fsum(x * x for x in w))
    return [x / norm for x in w]


def cosine(a: list[float], b: list[float]) -> float:
    """정규화 후 내적 — 큰 성분도 오버플로 없음. 0 벡터·비유한 성분이면 NaN(실패로 셈)."""
    return math.fsum(x * y for x, y in zip(_unit(a), _unit(b), strict=True))


def passes(cos: float) -> bool:
    return math.isfinite(cos) and cos >= MIN_COS


def recheck(stored: dict[str, tuple[str, list[float]]], settings: Settings) -> dict[str, Any]:
    """다시 임베딩해 저장 벡터와 대조 — {chunks, min_cos, below}. 임베딩 모델 불일치는 예외 그대로(중단)."""
    ids = sorted(stored)
    fresh = HttpEmbeddingClient(settings).embed([stored[c][0] for c in ids]) if ids else []
    cos = {c: cosine(stored[c][1], v) for c, v in zip(ids, fresh, strict=True)}
    finite = [v for v in cos.values() if math.isfinite(v)]
    return {
        "chunks": len(ids),
        "min_cos": round(min(finite), 6) if finite else None,
        "below": sum(not passes(v) for v in cos.values()),  # 비유한 포함
    }


def recheck_problem(summary: dict[str, Any]) -> str | None:
    if not summary["chunks"]:
        return "코퍼스 재임베딩 대조 대상 0 청크 — 유형 필터·모델 확인"
    if summary["below"]:
        return f"코퍼스 재임베딩 대조 실패 — {summary['below']}/{summary['chunks']} 청크 cos < {MIN_COS}"
    return None


def embed_query(text: str, settings: Settings, dry: bool) -> PreparedEmbedding:
    """(a) 임베딩 — 실측은 응답 본문 `model` 이 질의 모델(= DB 모델, 정규화한 값)과 같아야. 없거나 다르면 후보 검색 전 중단."""
    queries = [SearchQuery("a", "en", text)]
    if dry:
        return prepare(queries, settings, dry=True)
    try:  # 공통 클라이언트가 배치마다 응답 모델 = 정규화 요청 모델일 때만 벡터를 줌(검토 4)
        vectors = HttpEmbeddingClient(settings).embed([text])
    except EmbeddingModelMismatch:
        raise ValueError("임베딩 응답 모델이 질의·DB 모델과 다르거나 없음 — 후보 검색 전 중단") from None
    return PreparedEmbedding(queries, vectors, settings.embedding_model.strip())
