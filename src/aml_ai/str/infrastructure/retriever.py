"""RAG 검색 (docs/str/10). 질의 1줄 → 임베딩 1회 → pgvector top-3 (유형 필터 우선). 실패·0건 → [].

enabled=False (RAG_ENABLED) 면 항상 [] — 안건 22 되돌림 조건의 스위치.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient
from aml_ai.shared.schemas.str import Facts, Reference
from aml_ai.str.domain.constants import (
    MIN_SIMILARITY,
    RAG_CANDIDATES,
    RAG_TOP_K,
    REFERENCE_TEXT_MAX_CHARS,
)

TYPOLOGY_KO = {
    "FAN_IN": "집중 입금",
    "FAN_OUT": "분산 송금",
    "PASS_THROUGH": "경유 송금",
    "CYCLE": "순환 거래",
    "SCATTER_GATHER": "흩었다 모으기",
    "GATHER_SCATTER": "모았다 흩기",
    "STACK": "다단계 경유",
    "BIPARTITE": "집단 간 교차 송금",
    "STRUCTURING": "분할 거래",
    "NEW_ACCOUNT_LARGE": "신규 계좌 거액 송금",
    "HIGH_VALUE": "고액 단건",
    "DORMANT_BURST": "휴면 후 급증",
}

# SCRUM-126 — 유형별 영문 패턴 한 문장. 코퍼스가 영문이라 유형 이름만으로는 임베딩 매칭이 약함.
# ★L-1 baseline(유형 이름만 + model_signals): FAN_OUT·CYCLE hit 0, FAN_IN precision 0.33.
TYPOLOGY_PATTERN_EN = {
    "FAN_IN": "many senders deposit into one account",
    "FAN_OUT": "one account sends funds to many beneficiaries",
    "CYCLE": "funds move through accounts and return to the originating account",
    "SCATTER_GATHER": "funds are split across intermediate accounts and later consolidated into one account",
    "GATHER_SCATTER": "funds are pooled into one account and then distributed to many accounts",
}


def build_query(facts: Facts) -> str:
    """'{유형 한국어} {유형 영문 코드} {영문 패턴} {model_signals 이름} {industry}'.

    SCRUM-126 — 유형별 영문 패턴 한 문장 추가 (코퍼스 임베딩과 매칭 강화).
    """
    code = facts.typology.value if facts.typology else ""
    pattern = TYPOLOGY_PATTERN_EN.get(code, "")
    signals = " ".join(facts.model_signals)
    industry = facts.customer.industry if facts.customer and facts.customer.industry else ""
    return " ".join(p for p in (TYPOLOGY_KO.get(code, ""), code, pattern, signals, industry) if p)


class Retriever:
    def __init__(
        self, session: Session, embedder: EmbeddingClient, *, enabled: bool, k: int = RAG_TOP_K
    ) -> None:
        self._s = session
        self._embed = embedder
        self._enabled = enabled
        self._k = k

    def retrieve(self, facts: Facts) -> list[Reference]:
        if not self._enabled or facts.typology is None:
            return []
        vec = self._embed.embed([build_query(facts)])[0]  # RetrievalUnavailable 은 호출자가 잡아 [] 로
        return self._search(vec, facts.typology.value)

    def _search(self, vec: list[float], typology: str | None) -> list[Reference]:
        if typology is None:
            return []
        try:
            with self._s.begin_nested():
                self._s.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
                rows = self._s.execute(
                    text(
                        "WITH r AS MATERIALIZED ("
                        "  SELECT chunk_id, doc_id, doc_title, page, text, "
                        "         embedding <=> CAST(:vec AS vector) AS d "
                        "  FROM ai.reference_chunks WHERE typologies @> ARRAY[:ty]::text[] "
                        "  ORDER BY embedding <=> CAST(:vec AS vector) "
                        "  LIMIT :cand"
                        ") "
                        "SELECT chunk_id, doc_id, doc_title, page, text, 1 - d AS score "
                        "FROM r ORDER BY d + 0 LIMIT :k"
                    ),
                    {"vec": str(vec), "ty": typology, "k": self._k, "cand": RAG_CANDIDATES},
                ).all()
        except SQLAlchemyError as exc:
            raise RetrievalUnavailable("rag search failed") from exc
        return [
            Reference(
                chunk_id=row.chunk_id,
                doc_id=row.doc_id,
                doc_title=row.doc_title,
                page=row.page,
                score=float(row.score),
                text=(row.text or "")[:REFERENCE_TEXT_MAX_CHARS],
            )
            for row in rows
            if row.score is not None and row.score >= MIN_SIMILARITY
        ]
