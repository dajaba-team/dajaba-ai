"""ai.verification_runs 쓰기."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from aml_ai.shared.schemas.str import CodeCheck, JudgeMeta, LlmCheck, VerifyStatus
from aml_ai.str.infrastructure.orm import VerificationRun


class VerificationRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def save(
        self,
        *,
        generation_id: str,
        draft_id: str,
        revision_no: int,
        code_checks: list[CodeCheck],
        llm_checks: list[LlmCheck] | None,
        passed: bool,
        status: VerifyStatus,
        verifier_version: str,
        narrative_sha256: str,
        request_id: str | None,
        judge_meta: JudgeMeta | None = None,
    ) -> str:
        vid = uuid.uuid4().hex
        self._s.add(
            VerificationRun(
                verification_id=vid,
                generation_id=generation_id,
                draft_id=draft_id,
                revision_no=revision_no,
                code_checks=[c.model_dump(mode="json") for c in code_checks],
                llm_checks=(
                    [c.model_dump(mode="json") for c in llm_checks] if llm_checks is not None else None
                ),
                passed=passed,
                status=status.value,
                verifier_version=verifier_version,
                narrative_sha256=narrative_sha256,
                request_id=request_id,
                judge_llm_model=judge_meta.llm_model if judge_meta else None,
                judge_tokens_in=judge_meta.tokens_in if judge_meta else None,
                judge_tokens_out=judge_meta.tokens_out if judge_meta else None,
                judge_latency_ms=judge_meta.latency_ms if judge_meta else None,
                judge_attempts=judge_meta.attempts if judge_meta else None,
            )
        )
        self._s.commit()
        return vid
