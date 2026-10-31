"""POST /v1/str/verify 처리 순서 (docs/str/03, 06).

1 generations 에서 생성 당시 facts·evidence_transaction_ids → 2 본문 해시 → 3 코드 5종(순수)
→ 4 전부 통과 시 judge(마스킹본) → 5 passed/status → 6 저장 → 7 응답
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import DraftNotFound, LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.hashing import narrative_sha256
from aml_ai.shared.infrastructure.llm_client import make_llm_client
from aml_ai.shared.schemas.str import LlmCheck, VerifyRequest, VerifyResponse, VerifyStatus
from aml_ai.str.domain import masking, verification
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE, VERIFIER_VERSION
from aml_ai.str.domain.models import StoredDraft
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
        draft = self.generations.load_draft(req.generation_id)
        if draft is None:
            raise DraftNotFound(f"generation {req.generation_id} not found")

        sha = narrative_sha256(req.narrative)
        code_checks = verification.run_code_checks(draft.facts, req.narrative, draft.evidence_transaction_ids)
        code_ok = all(c.match for c in code_checks)

        status, llm_checks = self._decide(draft, req, code_ok)

        passed = status is VerifyStatus.PASSED
        verifier_version = f"{VERIFIER_VERSION}+{self.judge.prompt_version}"
        vid = self.verifications.save(
            generation_id=draft.generation_id,
            draft_id=draft.draft_id,
            revision_no=req.revision_no,
            code_checks=code_checks,
            llm_checks=llm_checks,
            passed=passed,
            status=status,
            verifier_version=verifier_version,
        )
        return VerifyResponse(
            verification_id=vid,
            generation_id=draft.generation_id,
            revision_no=req.revision_no,
            narrative_sha256=sha,
            passed=passed,
            status=status,
            code_checks=code_checks,
            llm_checks=llm_checks,
            narrative_refs=None,  # TODO(Open-23): judge_v2 섹션별 cites → attach_evidence (W3)
            verifier_version=verifier_version,
            produced_at=datetime.now().replace(microsecond=0),
        )

    def _decide(
        self, draft: StoredDraft, req: VerifyRequest, code_ok: bool
    ) -> tuple[VerifyStatus, list[LlmCheck] | None]:
        llm_checks: list[LlmCheck] | None = None
        if not code_ok:
            status = VerifyStatus.CODE_FAILED  # 평가자 안 부름 — 비용, 어차피 fail
        else:
            try:
                llm_checks = self.judge.run(masking.mask_for_llm(draft.facts), req.narrative)
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

        return status, llm_checks
