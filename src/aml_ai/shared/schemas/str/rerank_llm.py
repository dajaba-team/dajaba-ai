"""참고 사례 리랭커 LLM 출력 — rerank_v1 (SCRUM-308-2). 정본 docs/str/05 "rerank_v1"·str/10 "리랭커".

규약 JSON 이 아니라 LLM Structured Output 모양. 표지 순열인지는 `str/domain/rag_rerank` 가 본다 —
다른 칸이 있으면(StrictModel extra=forbid) 여기서 거절 → 호출 측이 원래 순서(fail-open).
"""

from __future__ import annotations

from pydantic import Field

from aml_ai.shared.schemas.common import StrictModel

RERANK_ORDER_MAX = 10  # = str/domain/constants.RAG_CANDIDATES (테스트가 대조 — shared 는 str 을 import 안 함)


class RerankOut(StrictModel):
    order: list[str] = Field(min_length=1, max_length=RERANK_ORDER_MAX)
