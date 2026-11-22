"""승인 STR 색인 저장소 — `ai.str_reference_docs`(부모) · `ai.str_reference_chunks` (SCRUM-310, docs/str/10 "승인 STR 색인").

읽기(임베딩 전): 같은 번호 부모 행 · 그 초안 facts 로 케이스 계좌(거래가 다 있는지 확인) · 원천 계좌 표 정확 일치(쿼리 한 번)
→ `release` 로 연결 반납 — 모두 같은 DB 오류 처리(503). 쓰기: READ COMMITTED 를 트랜잭션 첫 문장으로 → 문서번호 advisory 잠금 → 부모 다시 확인 → 부모 +
섹션 행 → 커밋. 부모 PK 가 같은 번호 두 벌을 막음(격리 수준과 상관없이, 추가 검토 2) — 충돌이면 이미 있던 부모를 돌려줌.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from aml_ai.shared.db import end_read
from aml_ai.shared.errors import DbUnavailable
from aml_ai.str.domain.str_index import case_seed

_FACTS = text(
    "SELECT facts FROM ai.generations WHERE draft_id = :d AND kind = 'DRAFT' AND status = 'SUCCEEDED' "
    "ORDER BY created_at DESC LIMIT 1"
)
_TX_ACCOUNTS = text(
    "SELECT transaction_id, from_account_key, to_account_key FROM ops.transactions WHERE transaction_id = ANY(:ids)"
)
_ANY_ACCOUNT = text(
    "SELECT 1 FROM ops.accounts WHERE upper(replace(account_key, '_', '')) = ANY(:c) "
    "OR upper(split_part(account_key, '_', 2)) = ANY(:c) LIMIT 1"
)
_DOC = text(
    "SELECT request_hash, chunk_count, retrieval_version FROM ai.str_reference_docs WHERE report_no = :r"
)
_READ_COMMITTED = text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
_LOCK = text("SELECT pg_advisory_xact_lock(hashtext(:r))")
_INSERT_DOC = text(
    "INSERT INTO ai.str_reference_docs (report_no, draft_id, section_set, typologies, request_hash, retrieval_version, "
    "chunk_count, approved_at) VALUES (:r, :d, :set, CAST(:tys AS text[]), :hash, :version, :n, :approved_at)"
)
_INSERT_CHUNK = text(
    "INSERT INTO ai.str_reference_chunks (chunk_id, report_no, section, typologies, text, embedding, embedding_model) "
    "VALUES (:chunk_id, :r, :section, CAST(:tys AS text[]), :text, CAST(:embedding AS vector), :model)"
)


@dataclass(frozen=True)
class Stored:
    request_hash: str
    chunk_count: int
    retrieval_version: str  # 색인 때 값 — 재요청은 이 값을 돌려줌(모델이 바뀌어도, 추가 검토 1)


@dataclass(frozen=True)
class NewChunk:
    chunk_id: str
    section: str
    text: str
    embedding: list[float]


@dataclass(frozen=True)
class NewDoc:
    report_no: str
    draft_id: str
    section_set: str
    typologies: list[str]
    request_hash: str
    retrieval_version: str
    approved_at: datetime
    model: str
    chunks: list[NewChunk]


class StrIndexRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def case_accounts(self, draft_id: str) -> set[str] | None:
        """그 초안 facts 의 대상 계좌 + 거래 ID 로 읽은 보낸·받은 계좌. facts 가 없으면 None(→ NO_FACTS)."""
        try:
            facts = self._s.execute(_FACTS, {"d": draft_id}).scalar_one_or_none()
            if not isinstance(facts, dict):
                return None
            subject, ids = case_seed(facts)
            rows = self._s.execute(_TX_ACCOUNTS, {"ids": ids}).all() if ids else []
        except SQLAlchemyError as exc:
            raise DbUnavailable("str index facts read failed", error_type=type(exc).__name__) from exc
        # facts 거래가 하나라도 빠지거나 송·수신 계좌가 비면 대조를 끝낸 것으로 치지 않음 — 임베딩 전 503(검토 3)
        if {r.transaction_id for r in rows} != set(ids) or any(
            not (r.from_account_key and r.to_account_key) for r in rows
        ):
            raise DbUnavailable("str index source transactions incomplete")
        return {k for r in rows for k in (r.from_account_key, r.to_account_key)} | (
            {subject} if subject else set()
        )

    def any_account(self, candidates: list[str]) -> bool:
        if not candidates:
            return False
        try:
            return self._s.execute(_ANY_ACCOUNT, {"c": candidates}).first() is not None
        except SQLAlchemyError as exc:
            raise DbUnavailable("str index account check failed", error_type=type(exc).__name__) from exc

    def existing(self, report_no: str) -> Stored | None:
        """같은 번호 부모 행(읽기만) — 서비스가 계좌 검사보다 먼저 봄(검토 3 M6)."""
        try:
            row = self._s.execute(_DOC, {"r": report_no}).first()
        except SQLAlchemyError as exc:
            raise DbUnavailable("str index read failed", error_type=type(exc).__name__) from exc
        return Stored(row.request_hash, row.chunk_count, row.retrieval_version) if row else None

    def release(self) -> None:
        """읽기를 다 한 뒤 임베딩(외부 호출) 전에 연결 반납 — 실패도 503(추가 검토 1)."""
        try:
            end_read(self._s)
        except SQLAlchemyError as exc:
            raise DbUnavailable("str index read release failed", error_type=type(exc).__name__) from exc

    def insert(self, doc: NewDoc) -> Stored:
        """넣었거나 이미 있던 부모. 이미 있던 해시가 다르면 호출 측이 400 으로."""
        try:
            self._s.execute(_READ_COMMITTED)  # 트랜잭션 첫 문장 — 잠금 뒤 다른 요청의 커밋이 보이게
            self._s.execute(_LOCK, {"r": doc.report_no})
            found = self._s.execute(_DOC, {"r": doc.report_no}).first()
            if found is not None:
                self._s.rollback()
                return Stored(found.request_hash, found.chunk_count, found.retrieval_version)
            self._write(doc)
            self._s.commit()
        except IntegrityError:
            self._s.rollback()  # 부모 PK 충돌 — 다른 요청이 먼저 넣음
            return self._after_conflict(doc.report_no)
        except SQLAlchemyError as exc:
            self._s.rollback()
            raise DbUnavailable("str index write failed", error_type=type(exc).__name__) from exc
        return Stored(doc.request_hash, len(doc.chunks), doc.retrieval_version)

    def _write(self, doc: NewDoc) -> None:
        self._s.execute(_INSERT_DOC, {"r": doc.report_no, "d": doc.draft_id, "set": doc.section_set,
                                      "tys": doc.typologies, "hash": doc.request_hash, "version": doc.retrieval_version,
                                      "n": len(doc.chunks), "approved_at": doc.approved_at})  # fmt: skip
        self._s.execute(_INSERT_CHUNK, [
            {"chunk_id": c.chunk_id, "r": doc.report_no, "section": c.section, "tys": doc.typologies, "text": c.text,
             "embedding": str(c.embedding), "model": doc.model}
            for c in doc.chunks
        ])  # fmt: skip

    def _after_conflict(self, report_no: str) -> Stored:
        try:
            row = self._s.execute(_DOC, {"r": report_no}).first()
            self._s.rollback()
        except SQLAlchemyError as exc:
            raise DbUnavailable("str index read failed", error_type=type(exc).__name__) from exc
        if row is None:
            raise DbUnavailable("str index conflict without row")
        return Stored(row.request_hash, row.chunk_count, row.retrieval_version)
