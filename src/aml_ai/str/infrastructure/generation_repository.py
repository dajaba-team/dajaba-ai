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
            request={
                "evidence_transaction_ids": req.evidence_transaction_ids,
                "prompt_vars": gen.request_payload,
            },
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

    def load_draft(self, generation_id: str) -> StoredDraft | None:
        """검증 요청의 generation_id → 생성 당시 facts. TODO(SCRUM-14): status=SUCCEEDED 조건."""
        stmt = select(Generation).where(Generation.generation_id == generation_id, Generation.kind == "DRAFT")
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
