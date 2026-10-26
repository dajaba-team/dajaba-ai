"""POST /v1/str/verify 처리 순서 (docs/str/03, 06).

2 generations 에서 facts·transaction_ids → 3 코드 4종(순수) → 4 전부 통과 시 judge → 5 passed/status → 6 저장 → 7 응답
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import DraftNotFound, LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.infrastructure.llm_client import make_llm_client
from aml_ai.shared.schemas.str import LlmCheck, VerifyRequest, VerifyResponse, VerifyStatus
from aml_ai.str.domain import verification
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE, VERIFIER_VERSION
from aml_ai.str.infrastructure.generation_repository import GenerationRepository
from aml_ai.str.infrastructure.judge import Judge
from aml_ai.str.infrastructure.verification_repository import VerificationRepository

log = logging.getLogger(__name__)


@dataclass
class VerifyService:
    settings: Settings
    generations: GenerationRepository
    verifications: VerificationRepository
    judge: Judge

    @classmethod
    def build(cls, session: Session, settings: Settings) -> VerifyService:
        return cls(
            settings=settings,
            generations=GenerationRepository(session),
            verifications=VerificationRepository(session),
            judge=Judge(make_llm_client(settings), settings),
        )

    def verify(self, req: VerifyRequest) -> VerifyResponse:
        draft = self.generations.load_latest_draft(req.draft_id)
        if draft is None:
            raise DraftNotFound(f"draft {req.draft_id} has no generation")

        code_checks = verification.run_code_checks(draft.facts, req.narrative, draft.transaction_ids)
        code_ok = all(c.match for c in code_checks)

        llm_checks: list[LlmCheck] | None = None
        if not code_ok:
            status = VerifyStatus.CODE_FAILED  # 평가자 안 부름 — 비용, 어차피 fail
        else:
            try:
                llm_checks = self.judge.run(draft.facts, req.narrative)
                status = (
                    VerifyStatus.PASSED
                    if all(c.score >= JUDGE_PASS_SCORE for c in llm_checks)
                    else VerifyStatus.LLM_FAILED
                )
            except (LlmUnavailable, LlmInvalidOutput) as exc:
                log.warning("judge_unavailable", extra={"reason": exc.code})
                status = (
                    VerifyStatus.VERIFY_UNAVAILABLE
                )  # passed=false 가 아니다 — 백엔드 "다시 검증" (안건 9)

        passed = status is VerifyStatus.PASSED
        verifier_version = f"{VERIFIER_VERSION}+{self.judge.prompt_version}"
        vid = self.verifications.save(
            generation_id=draft.generation_id,
            draft_id=req.draft_id,
            revision_no=req.revision_no,
            code_checks=code_checks,
            llm_checks=llm_checks,
            passed=passed,
            status=status,
            verifier_version=verifier_version,
        )
        return VerifyResponse(
            verification_id=vid,
            passed=passed,
            status=status,
            code_checks=code_checks,
            llm_checks=llm_checks,
            verifier_version=verifier_version,
            produced_at=datetime.now().replace(microsecond=0),
        )
