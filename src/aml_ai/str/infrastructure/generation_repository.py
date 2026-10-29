"""ai.generations 선점·펜싱·조회 (docs/shared/03)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.errors import AiError, FencedOut, GenerationInProgress, InvalidRequest
from aml_ai.shared.logging import current_request_id
from aml_ai.shared.schemas.str import DraftRequest, DraftResponse, Facts, Reference
from aml_ai.str.domain.models import StoredDraft
from aml_ai.str.infrastructure.orm import Generation

log = logging.getLogger(__name__)
_ERROR_DETAIL_MAX = 48  # DB error 칸 — code 외 상수 설명만, pydantic 입력값 유출 방지


@dataclass(frozen=True)
class ClaimNew:
    generation_id: str


@dataclass(frozen=True)
class ClaimReuse:
    response: DraftResponse


ClaimResult = ClaimNew | ClaimReuse


class GenerationRepository:
    def __init__(self, session: Session, settings: Settings | None = None) -> None:
        self._s = session
        self._settings = settings or get_settings()

    def claim(self, req: DraftRequest, request_hash: str) -> ClaimResult:
        """잠금·STALE 정리·해시 비교·INSERT를 한 트랜잭션으로 커밋한다."""
        with self._s.begin():
            self._s.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('draft:' || :draft_id))"),
                {"draft_id": req.draft_id},
            )
            self._expire_stale(req.draft_id)
            mismatch = self._s.scalar(
                select(Generation.generation_id)
                .where(
                    Generation.kind == "DRAFT",
                    Generation.draft_id == req.draft_id,
                    Generation.request_hash != request_hash,
                )
                .limit(1)
            )
            if mismatch is not None:
                raise InvalidRequest("draft_id reused with different body")
            gid = self._insert_claim(req, request_hash)
            if gid is not None:
                return ClaimNew(gid)
            return self._reuse(req.draft_id, request_hash)

    def _expire_stale(self, draft_id: str) -> None:
        self._s.execute(
            update(Generation)
            .where(
                Generation.kind == "DRAFT",
                Generation.draft_id == draft_id,
                Generation.status == "PROCESSING",
                Generation.created_at < func.now() - timedelta(seconds=self._settings.stale_processing_s),
            )
            .values(status="FAILED", error="STALE_PROCESSING", finished_at=func.now())
        )

    def _insert_claim(self, req: DraftRequest, request_hash: str) -> str | None:
        stmt = (
            insert(Generation)
            .values(
                generation_id=uuid.uuid4().hex,
                kind="DRAFT",
                draft_id=req.draft_id,
                case_no=req.case_no,
                request=req.model_dump(mode="json"),
                request_hash=request_hash,
                status="PROCESSING",
                request_id=current_request_id(),
            )
            .on_conflict_do_nothing(
                index_elements=[Generation.draft_id],
                index_where=text("kind='DRAFT' AND status <> 'FAILED'"),
            )
            .returning(Generation.generation_id)
        )
        return self._s.execute(stmt).scalar_one_or_none()

    def _reuse(self, draft_id: str, request_hash: str) -> ClaimReuse:
        row = self._s.execute(
            select(Generation)
            .where(
                Generation.kind == "DRAFT",
                Generation.draft_id == draft_id,
                Generation.status != "FAILED",
            )
            .execution_options(populate_existing=True)
        ).scalar_one()
        if row.request_hash != request_hash:
            raise InvalidRequest("draft_id reused with different body")
        if row.status != "SUCCEEDED":
            raise GenerationInProgress()
        try:
            response = DraftResponse.model_validate(row.response)
        except ValidationError:
            # 저장된 응답이 지금 스키마에 안 맞음 — 500 INTERNAL. 로그는 generation_id 만.
            log.warning("stored_draft_response_corrupted", extra={"generation_id": row.generation_id})
            raise AiError("stored draft response schema mismatch") from None
        return ClaimReuse(response)

    def finish(
        self,
        generation_id: str,
        *,
        facts: Facts,
        response_payload: dict[str, object],
        meta: dict[str, object],
    ) -> None:
        """PROCESSING인 자기 시도만 SUCCEEDED로 닫는다."""
        columns = (
            "llm_model",
            "prompt_version",
            "few_shot_ids",
            "references",
            "retrieval_version",
            "tokens_in",
            "tokens_out",
            "latency_ms",
        )
        values = {key: meta[key] for key in columns if key in meta}
        values.update(status="SUCCEEDED", facts=facts.model_dump(mode="json"), response=response_payload)
        self._close(generation_id, values)

    def fail(self, generation_id: str, *, code: str, message: str = "") -> None:
        """FAILED 로 닫는다. error 는 code + 짧은 상수 설명(최대 48자, 첫 줄만).

        message 는 짧은 상수만. pydantic/traceback 전문을 넘기면 입력값이 DB에 남는다 — 그래서 자른다.
        상세는 호출자가 로그로. loader 등의 더러워진 읽기 트랜잭션을 끝내고 실패 기록.
        """
        self._s.rollback()
        detail = message.replace("\n", " ")[:_ERROR_DETAIL_MAX].strip()
        error_text = f"{code}: {detail}" if detail else code
        self._close(generation_id, {"status": "FAILED", "error": error_text})

    def _close(self, generation_id: str, values: dict[str, object]) -> None:
        try:
            result = self._s.execute(
                update(Generation)
                .where(
                    Generation.generation_id == generation_id,
                    Generation.status == "PROCESSING",
                )
                .values(**values, finished_at=func.now())
            )
            if result.rowcount == 0:
                raise FencedOut(generation_id)
            self._s.commit()
        except Exception:
            self._s.rollback()
            raise

    def load_draft(self, generation_id: str) -> StoredDraft | None:
        stmt = select(Generation).where(
            Generation.generation_id == generation_id,
            Generation.kind == "DRAFT",
            Generation.status == "SUCCEEDED",
        )
        row = self._s.execute(stmt).scalar_one_or_none()
        if row is None or row.facts is None:
            return None
        return StoredDraft(
            generation_id=row.generation_id,
            draft_id=row.draft_id,
            facts=Facts.model_validate(row.facts),
            evidence_transaction_ids=list(row.request.get("evidence_transaction_ids", [])),
            references=[Reference.model_validate(r) for r in (row.references or [])],
        )
