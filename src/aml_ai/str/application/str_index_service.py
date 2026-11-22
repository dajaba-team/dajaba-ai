"""`/v1/references/str` — 승인 STR 색인 (SCRUM-310, 정본 docs/str/03·10 "승인 STR 색인"). LLM 0, 임베딩 0~1회.

스위치 → 같은 번호(저장된 결과 또는 400, 검토 3) → 명시적 계좌 키 → 짧음 → 그 초안 facts 케이스 계좌(없으면 NO_FACTS) →
케이스 계좌 조각 → 원천 계좌 표 정확 일치 → 연결 반납 → 임베딩(섹션 n개 한 번에) → 한 트랜잭션 저장. 계좌 검사는 실제 계좌 대조(추가 검토 2).
`SKIPPED` 는 행을 남기지 않음. `ai.generations` 0. 로그는 문서번호·섹션 세트·섹션 수·청크 수·상태·지연만(본문 0).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import InvalidRequest, LlmUnavailable, RetrievalUnavailable
from aml_ai.shared.infrastructure.embedding_client import EmbeddingClient, HttpEmbeddingClient
from aml_ai.shared.schemas.str import StrIndexRequest, StrIndexResponse, StrIndexSkipReason, StrIndexStatus
from aml_ai.shared.time_utils import utc_now
from aml_ai.str.domain.constants_rag_query import STR_INDEX_MIN_CHARS
from aml_ai.str.domain.raw_account import case_fragment_hit, exact_candidates, explicit_key
from aml_ai.str.domain.str_index import chunk_id, chunks, content_chars, request_hash, section_texts
from aml_ai.str.infrastructure import str_index_runtime as runtime
from aml_ai.str.infrastructure.str_index_repository import NewChunk, NewDoc, Stored, StrIndexRepository

log = logging.getLogger(__name__)
_MS = 1000
_DIFFERENT_BODY = "report_no already indexed with a different body"
Skip = StrIndexSkipReason


@dataclass
class StrIndexService:
    settings: Settings
    repo: StrIndexRepository
    embedder: EmbeddingClient
    retrieval_version: str | None  # 기동 때 고정(검토 2 M6) — 꺼져 있으면 None
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def build(cls, session: Session, settings: Settings) -> StrIndexService:
        return cls(settings=settings, repo=StrIndexRepository(session), embedder=HttpEmbeddingClient(settings),
                   retrieval_version=runtime.version())  # fmt: skip

    def index(self, req: StrIndexRequest) -> StrIndexResponse:
        started = self.clock()
        if not (self.settings.rag_enabled and self.settings.str_index_enabled):
            return self._skipped(req, Skip.DISABLED, started)
        if self.retrieval_version is None:
            raise RuntimeError("str index not started")  # 기동 검사·lifespan 이 막음 — 여기 오면 설정 버그
        digest = request_hash(req)
        found = self.repo.existing(req.report_no)  # 같은 번호가 먼저 — 저장된 결과 또는 400(검토 3 M6)
        if found is not None:
            self.repo.release()
            return self._same_or_400(req, digest, found, started)
        reason = self._skip_reason(req, section_texts(req))  # 계좌 원문·짧음은 나누기 전(SCRUM-361)
        self.repo.release()  # 읽기 끝 — 임베딩(외부 호출) 중 연결 안 듦
        if reason is not None:
            return self._skipped(req, reason, started)
        pieces = chunks(req)  # 섹션마다 ≤1200 청크(SCRUM-361)
        vectors = self._embed([t for _, _, t in pieces])
        stored = self.repo.insert(NewDoc(
            report_no=req.report_no, draft_id=req.draft_id, section_set=req.section_set,
            typologies=[t.value for t in req.typologies], request_hash=digest, retrieval_version=self.retrieval_version,
            approved_at=req.approved_at, model=self.embedder.model,
            chunks=[NewChunk(chunk_id(req.report_no, s, n), s, n, t, v) for (s, n, t), v in zip(pieces, vectors, strict=True)],
        ))  # fmt: skip
        return self._same_or_400(req, digest, stored, started)

    def _skip_reason(self, req: StrIndexRequest, texts: list[str]) -> StrIndexSkipReason | None:
        """계좌 원문(실제 계좌 대조) · 짧음 · facts 없음. DB 조회 실패는 503(실패 쪽으로 닫음)."""
        if explicit_key(texts):
            return Skip.RAW_ACCOUNT
        if content_chars(req) < STR_INDEX_MIN_CHARS:
            return Skip.TOO_SHORT
        accounts = self.repo.case_accounts(req.draft_id)
        if accounts is None:
            return Skip.NO_FACTS
        if case_fragment_hit(texts, accounts) or self.repo.any_account(exact_candidates(texts)):
            return Skip.RAW_ACCOUNT
        return None

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            vectors = self.embedder.embed(texts)
        except RetrievalUnavailable as exc:
            log.warning("str_index_failed", extra={"reason": "embedding", "error_type": type(exc).__name__})
            raise LlmUnavailable("str index embedding failed") from exc
        if len(vectors) != len(texts):
            raise LlmUnavailable("str index embedding count mismatch")
        return vectors

    def _same_or_400(
        self, req: StrIndexRequest, digest: str, stored: Stored, started: float
    ) -> StrIndexResponse:
        """기존·방금 넣은 행 — 응답 버전은 저장된 값(색인 때 모델, 추가 검토 1)."""
        if stored.request_hash != digest:
            log.warning("str_index_failed", extra={"reason": "different_body", "report_no": req.report_no})
            raise InvalidRequest(_DIFFERENT_BODY)
        self._log("str_index_done", req, StrIndexStatus.INDEXED, None, stored.chunk_count, started)
        return StrIndexResponse(produced_at=utc_now(), report_no=req.report_no, status=StrIndexStatus.INDEXED,
                                skip_reason=None, chunk_count=stored.chunk_count,
                                retrieval_version=stored.retrieval_version)  # fmt: skip

    def _skipped(self, req: StrIndexRequest, reason: StrIndexSkipReason, started: float) -> StrIndexResponse:
        self._log("str_index_skipped", req, StrIndexStatus.SKIPPED, reason, 0, started)
        return StrIndexResponse(produced_at=utc_now(), report_no=req.report_no, status=StrIndexStatus.SKIPPED,
                                skip_reason=reason, chunk_count=0, retrieval_version=self.retrieval_version)  # fmt: skip

    def _log(self, msg: str, req: StrIndexRequest, status: StrIndexStatus, reason: StrIndexSkipReason | None,
             count: int, started: float) -> None:  # fmt: skip
        log.info(msg, extra={
            "report_no": req.report_no, "section_set": req.section_set, "sections": len(req.sections),
            "chunks": count, "status": status.value, "skip_reason": reason.value if reason else None,
            "latency_ms": int((self.clock() - started) * _MS),
        })  # fmt: skip
