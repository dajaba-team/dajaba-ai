"""요약 `generations` 행 저장 (SCRUM-129) — 선점·펜싱 없음, 매번 새 행."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from aml_ai.shared.logging import current_request_id
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.orm import Generation

_META_COLS = ("llm_model", "prompt_version", "few_shot_ids", "tokens_in", "tokens_out", "latency_ms")


@dataclass
class SummaryRepository:
    session: Session

    def save(
        self,
        *,
        generation_id: str,
        case_no: str,
        request: dict[str, object],
        facts: Facts | None,
        response_payload: dict[str, object],
        meta: dict[str, object],
        status: str,
        error: str | None = None,
    ) -> None:
        """status=SUCCEEDED 또는 FAILED. facts 는 실패 저장에서 None 가능(ORM 칸이 nullable)."""
        values = {k: meta[k] for k in _META_COLS if k in meta}
        row = Generation(
            generation_id=generation_id,
            kind="SUMMARY",
            draft_id=None,
            case_no=case_no,
            request=request,
            request_hash="",  # 요약은 해시 없음(선점 안 함)
            facts=facts.model_dump(mode="json") if facts is not None else None,
            response=response_payload,
            status=status,
            error=error,
            request_id=current_request_id(),
            finished_at=func.now(),
            **values,
        )
        self.session.add(row)
        self.session.commit()
