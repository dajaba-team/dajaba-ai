"""`/v1/references/search` — 참고 사례 검색 (SCRUM-309, 정본 docs/str/03·10 "참고 사례 검색"). 조회 전용.

가리기 → 질의 한 줄 → 임베딩 0~1회(유형만이면 캐시) → 지금 표 검색 → 정리 → 응답. `ai.generations` 0.
DB 연결은 임베딩 뒤에 처음 씀(세션은 첫 실행 때 연결). 로그는 유형·길이·개수·지연·캐시만 — 검색어·청크 본문 0.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.schemas.str import (
    ReferenceResult,
    ReferenceSearchMeta,
    ReferenceSearchRequest,
    ReferenceSearchResponse,
    ReferenceSearchStatus,
    ReferenceSourceType,
)
from aml_ai.shared.text import utf16_len_nfc
from aml_ai.shared.time_utils import utc_now
from aml_ai.str.domain.constants_rag_query import (
    REFERENCE_CACHE_MAX,
    REFERENCE_PER_DOC_MAX,
    REFERENCE_QUERY_VERSION,
)
from aml_ai.str.domain.reference_search import Hit, arrange, masked_query, query_text
from aml_ai.str.infrastructure import reference_search_runtime as runtime
from aml_ai.str.infrastructure.reference_embedding import embed_within
from aml_ai.str.infrastructure.reference_search_repository import ReferenceSearchRepository

log = logging.getLogger(__name__)
_MS = 1000


class EmbeddingCache:
    """유형만 쓴 질의의 벡터 — 키 (정렬 유형, 임베딩 모델, 질의 버전). 프로세스 안, 오래된 것부터 버림."""

    def __init__(self, size: int) -> None:
        self._size, self._items, self._lock = size, OrderedDict[tuple, list[float]](), threading.Lock()

    def get(self, key: tuple) -> list[float] | None:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
            return None

    def put(self, key: tuple, vec: list[float]) -> None:
        with self._lock:
            self._items[key] = vec
            self._items.move_to_end(key)
            while len(self._items) > self._size:
                self._items.popitem(last=False)


CACHE = EmbeddingCache(REFERENCE_CACHE_MAX)


def search_deadline(settings: Settings, budget_ms: int | None, started: float) -> float:
    """절대 마감(단조) = 들어온 시각 + min(`REFERENCE_SEARCH_BUDGET_S`, `X-Budget-Ms`). 서비스·응답 경계 래퍼가 같은 값."""
    budget_s = settings.reference_search_budget_s
    return started + (min(budget_s, budget_ms / _MS) if budget_ms is not None else budget_s)


@dataclass
class ReferenceSearchService:
    settings: Settings
    repo: ReferenceSearchRepository
    embed: Callable[[str, float], list[float]]  # (문장, 절대 마감) → 벡터 — 실패는 502 예외(검토 3)
    retrieval_version: str  # 기동 검사 때 읽은 값(검토 2 — 요청마다 manifest 안 읽음)
    clock: Callable[[], float] = time.monotonic
    cache: EmbeddingCache = field(default_factory=lambda: CACHE)

    @classmethod
    def build(cls, session: Session, settings: Settings) -> ReferenceSearchService:
        def embed(text: str, deadline: float) -> list[float]:
            return embed_within(settings, text, deadline)

        repo = ReferenceSearchRepository(session)
        return cls(settings=settings, repo=repo, embed=embed, retrieval_version=runtime.version())

    def search(
        self, req: ReferenceSearchRequest, budget_ms: int | None, received_at: float | None = None
    ) -> ReferenceSearchResponse:
        """`received_at` = 요청이 들어온 시각(미들웨어, 단조) — 마감·지연은 여기서부터(검토 2). 없으면 지금."""
        started = self.clock() if received_at is None else received_at
        deadline = search_deadline(self.settings, budget_ms, started)
        self._remaining(deadline)  # 작업 스레드를 기다리다 만료 — 임베딩·DB 전에 502
        typologies = [t.value for t in req.typologies]
        masked = masked_query(req.query)
        vec, cache_hit = self._vector(typologies, masked, deadline)
        self._remaining(deadline)  # DB 전(캐시 적중 포함)
        hits = self.repo.search(vec, typologies, self._model(), deadline=deadline, clock=self.clock)
        picked = arrange(hits, top_k=req.top_k, per_doc=REFERENCE_PER_DOC_MAX)
        response = self._response(picked, len(hits), started)
        try:
            self._remaining(deadline)  # 조립·검증 뒤, 성공 반환 직전 — 넘었으면 200 대신 502(검토 2)
        except LlmUnavailable:
            log.warning(
                "reference_search_failed",
                extra={"reason": "budget", "latency_ms": response.search_meta.latency_ms},
            )
            raise
        log.info("reference_search_done", extra={
            "typologies": sorted(typologies), "query_len": utf16_len_nfc(req.query) if req.query else 0,
            "results": len(picked), "candidates": len(hits), "latency_ms": response.search_meta.latency_ms,
            "cache_hit": cache_hit,
        })  # fmt: skip
        return response

    def _model(self) -> str:
        return self.settings.embedding_model.strip()

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise LlmUnavailable("reference search budget exhausted")
        return remaining

    def _vector(self, typologies: list[str], masked: str | None, deadline: float) -> tuple[list[float], bool]:
        key = (tuple(sorted(typologies)), self._model(), REFERENCE_QUERY_VERSION) if masked is None else None
        if key is not None and (cached := self.cache.get(key)) is not None:
            return cached, True
        self._remaining(deadline)
        until = min(self.clock() + self.settings.reference_search_embed_timeout_s, deadline)
        vec = self.embed(query_text(typologies, masked), until)  # 전송·본문 전체 한 절대 마감(추가 검토 1·3)
        self._remaining(deadline)
        if key is not None:
            self.cache.put(key, vec)
        return vec, False

    def _response(self, picked: list[Hit], candidates: int, started: float) -> ReferenceSearchResponse:
        return ReferenceSearchResponse(
            produced_at=utc_now(),
            status=ReferenceSearchStatus.FOUND if picked else ReferenceSearchStatus.EMPTY,
            results=[
                ReferenceResult(
                    doc_id=h.doc_id,
                    doc_title=h.doc_title,
                    publisher=h.publisher,
                    year=h.year,
                    page=h.page,
                    score=h.score,
                    chunk_id=h.chunk_id,
                    typologies=list(h.typologies),
                    source_type=ReferenceSourceType.PUBLIC,
                )
                for h in picked
            ],  # fmt: skip
            retrieval_version=self.retrieval_version,
            search_meta=ReferenceSearchMeta(
                degraded=False, candidates=candidates, latency_ms=int((self.clock() - started) * _MS)
            ),
        )
