"""RAG 검색 (docs/str/10). 질의 1줄 → 임베딩 1회 → pgvector top-3 (유형 필터 우선). 실패·0건 → [].

enabled=False (RAG_ENABLED) 면 항상 [] — 안건 22 되돌림 조건의 스위치.
TODO(W4): reference_chunks ORM + SQL. pgvector 확장은 백엔드 db/init 뒤.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient
from aml_ai.shared.schemas.str import Facts, Reference
from aml_ai.str.domain.constants import RAG_TOP_K

TYPOLOGY_KO = {
    "FAN_IN": "집중 입금",
    "FAN_OUT": "분산 송금",
    "PASS_THROUGH": "경유 송금",
    "CYCLE": "순환 거래",
    "STACK": "다단계 경유",
    "BIPARTITE": "집단 간 교차 송금",
    "STRUCTURING": "분할 거래",
    "NEW_ACCOUNT_LARGE": "신규 계좌 거액 송금",
    "HIGH_VALUE": "고액 단건",
    "DORMANT_BURST": "휴면 후 급증",
}


def build_query(facts: Facts) -> str:
    """'{유형 한국어} {유형 영문 코드} {top_reasons 이름 3개} {industry}' — 코퍼스가 영문이라 코드도 넣는다."""
    reasons = " ".join(r.split("=")[0].strip() for r in facts.top_reasons)
    industry = facts.customer.industry if facts.customer and facts.customer.industry else ""
    return f"{TYPOLOGY_KO.get(facts.typology.value, '')} {facts.typology.value} {reasons} {industry}".strip()


class Retriever:
    def __init__(
        self, session: Session, embedder: EmbeddingClient, *, enabled: bool, k: int = RAG_TOP_K
    ) -> None:
        self._s = session
        self._embed = embedder
        self._enabled = enabled
        self._k = k

    def retrieve(self, facts: Facts) -> list[Reference]:
        if not self._enabled:
            return []
        vec = self._embed.embed([build_query(facts)])[0]  # RetrievalUnavailable 은 호출자가 잡아 [] 로
        return self._search(vec, facts.typology.value)

    def _search(self, vec: list[float], typology: str) -> list[Reference]:
        raise NotImplementedError("W4 — typologies @> ARRAY[:t] 필터 + cosine top-k, 부족하면 필터 없이 채움")
