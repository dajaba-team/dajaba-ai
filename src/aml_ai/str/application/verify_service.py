"""POST /v1/str/verify 처리 순서 (docs/str/03, 06).

1 generations 에서 생성 당시 facts·evidence_transaction_ids → 2 본문 해시 → 3 코드 5종(순수)
→ 4 전부 통과 시 judge(마스킹본) → 5 passed/status → 6 저장 → 7 응답
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.db import end_read
from aml_ai.shared.errors import AiError, DraftNotFound
from aml_ai.shared.hashing import narrative_sha256
from aml_ai.shared.infrastructure.llm_client import make_llm_client
from aml_ai.shared.logging import current_request_id
from aml_ai.shared.schemas.str import (
    JudgeMeta,
    LlmCheck,
    NarrativeRef,
    NarrativeRefLlm,
    VerifyRequest,
    VerifyResponse,
    VerifyStatus,
)
from aml_ai.shared.time_utils import utc_now
from aml_ai.str.domain import masking, verification
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE, JUDGE_VOTES, VERIFIER_VERSION
from aml_ai.str.domain.fact_keys import fact_keys as domain_fact_keys
from aml_ai.str.domain.models import StoredDraft
from aml_ai.str.infrastructure.generation_repository import GenerationRepository
from aml_ai.str.infrastructure.judge import Judge
from aml_ai.str.infrastructure.verification_repository import VerificationRepository

log = logging.getLogger(__name__)


@dataclass
class VerifyService:
    settings: Settings
    session: Session  # SCRUM-122 — end_read(self.session) 호출용
    generations: GenerationRepository
    verifications: VerificationRepository
    judge: Judge
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def build(
        cls, session: Session, settings: Settings, *, clock: Callable[[], float] = time.monotonic
    ) -> VerifyService:
        return cls(
            settings=settings,
            session=session,
            generations=GenerationRepository(session),
            verifications=VerificationRepository(session),
            judge=Judge(make_llm_client(settings), settings, clock=clock, votes=JUDGE_VOTES),
            clock=clock,
        )

    def verify(self, req: VerifyRequest) -> VerifyResponse:
        draft = self.generations.load_draft(req.generation_id)
        if draft is None:
            raise DraftNotFound(f"generation {req.generation_id} not found")
        deadline = self.clock() + self.settings.verify_budget_s
        sha = narrative_sha256(req.narrative)
        code_checks = verification.run_code_checks(draft.facts, req.narrative, draft.evidence_transaction_ids)
        code_ok = all(c.match for c in code_checks)
        # SCRUM-122 — LLM 호출 바로 앞. CODE_FAILED 경로도 end_read(저장은 autobegin).
        end_read(self.session)
        status, llm_checks, judge_meta, narrative_refs = self._decide(draft, req, code_ok, deadline)
        return self._persist_and_respond(
            draft, req, sha, code_checks, llm_checks, judge_meta, narrative_refs, status
        )

    def _persist_and_respond(
        self, draft, req, sha, code_checks, llm_checks, judge_meta, narrative_refs, status
    ):
        passed = status is VerifyStatus.PASSED
        verifier_version = f"{VERIFIER_VERSION}+{self.judge.prompt_version}"
        rid = current_request_id()
        vid = self.verifications.save(
            generation_id=draft.generation_id,
            draft_id=draft.draft_id,
            revision_no=req.revision_no,
            code_checks=code_checks,
            llm_checks=llm_checks,
            passed=passed,
            status=status,
            verifier_version=verifier_version,
            narrative_sha256=sha,
            request_id=None if rid == "-" else rid,
            judge_meta=judge_meta,
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
            narrative_refs=narrative_refs,
            verifier_version=verifier_version,
            produced_at=utc_now(),
            judge_meta=judge_meta if status in (VerifyStatus.PASSED, VerifyStatus.LLM_FAILED) else None,
        )

    def _decide(
        self, draft: StoredDraft, req: VerifyRequest, code_ok: bool, deadline: float
    ) -> tuple[VerifyStatus, list[LlmCheck] | None, JudgeMeta | None, list[NarrativeRef] | None]:
        if not code_ok:
            return VerifyStatus.CODE_FAILED, None, None, None
        facts_masked = masking.mask_for_llm(draft.facts)
        keys = domain_fact_keys(draft.facts)
        try:
            result = self.judge.run(
                facts_masked, req.narrative, deadline=deadline, fact_keys=list(keys.keys())
            )
        except Exception as exc:
            log.warning(
                "judge_unavailable",
                extra={"reason": exc.code if isinstance(exc, AiError) else type(exc).__name__},
            )
            return VerifyStatus.VERIFY_UNAVAILABLE, None, getattr(exc, "judge_meta", None), None
        refs = _narrative_refs(result.sections, keys, req)
        status = (
            VerifyStatus.PASSED
            if all(c.score >= JUDGE_PASS_SCORE for c in result.checks)
            else VerifyStatus.LLM_FAILED
        )
        return status, result.checks, result.meta, refs


def _narrative_refs(
    sections: list[NarrativeRefLlm],
    keys: dict[str, list[int]],
    req: VerifyRequest,
) -> list[NarrativeRef]:
    """judge_v2 sections → 요청 섹션 순서로 필터·evidence_ids 재계산 (docs/str/06 "수정본의 cites").

    목록 밖 cites 는 버리고 섹션마다 한 번만 `judge_cites_dropped` 경고(섹션·개수만, 키 이름·본문 안 찍음).
    """
    by_section = {s.section: s.cites for s in sections}
    refs: list[NarrativeRef] = []
    for req_sec in req.narrative:
        raw = by_section.get(req_sec.section, [])
        kept = [c for c in raw if c in keys]
        dropped = len(raw) - len(kept)
        if dropped:
            log.warning("judge_cites_dropped", extra={"section": req_sec.section.value, "count": dropped})
        evidence_ids = sorted({i for c in kept for i in keys[c]})
        refs.append(NarrativeRef(section=req_sec.section, cites=kept, evidence_ids=evidence_ids))
    return refs
