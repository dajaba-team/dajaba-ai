"""ai.generations 읽기·쓰기."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from aml_ai.shared.logging import current_request_id
from aml_ai.shared.schemas.str import DraftRequest, Facts, Reference
from aml_ai.str.domain.models import GenerationResult, StoredDraft
from aml_ai.str.infrastructure.orm import Generation


class GenerationRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def save_draft(
        self, req: DraftRequest, facts: Facts, gen: GenerationResult, meta: dict[str, object]
    ) -> str:
        gid = uuid.uuid4().hex
        row = Generation(
            generation_id=gid,
            kind="DRAFT",
            draft_id=req.draft_id,
            case_no=req.case_no,
            facts=facts.model_dump(mode="json"),
            request={"transaction_ids": req.transaction_ids, "prompt_vars": gen.request_payload},
            response={"narrative": [s.model_dump() for s in gen.narrative], "raw": gen.raw_response},
            llm_model=gen.llm_model,
            prompt_version=gen.prompt_version,
            few_shot_ids=list(meta.get("few_shot_ids", [])),  # type: ignore[arg-type]
            references=list(meta.get("references", [])),  # type: ignore[arg-type]
            retrieval_version=meta.get("retrieval_version"),  # type: ignore[arg-type]
            tokens_in=gen.tokens_in,
            tokens_out=gen.tokens_out,
            latency_ms=gen.latency_ms,
            status="OK",
            request_id=current_request_id(),
        )
        self._s.add(row)
        self._s.commit()
        return gid

    def load_latest_draft(self, draft_id: str) -> StoredDraft | None:
        stmt = (
            select(Generation)
            .where(Generation.draft_id == draft_id, Generation.kind == "DRAFT")
            .order_by(Generation.created_at.desc())
            .limit(1)
        )
        row = self._s.execute(stmt).scalar_one_or_none()
        if row is None or row.facts is None:
            return None
        return StoredDraft(
            generation_id=row.generation_id,
            draft_id=draft_id,
            facts=Facts.model_validate(row.facts),
            transaction_ids=list(row.request.get("transaction_ids", [])),
            references=[Reference.model_validate(r) for r in (row.references or [])],
        )
