"""draft_service — 선체크 실패 흐름의 DB 결과 (SCRUM-45).

선체크 자체는 `test_narrative_generator_budget.py` 가 가짜 시계로 확인한다. 이 테스트는
draft_service 가 `LlmUnavailable` 을 받았을 때 generations 행을 **FAILED(LLM_UNAVAILABLE)** 로
닫는지, 그리고 같은 `draft_id` 로 다시 들어온 요청이 **409 아니라 새 `generation_id` 로 `ClaimNew`**
되는지(선점 ② "FAILED 뒤 재시도"가 draft_service 경로의 LlmUnavailable 에서도 유지되는지)만.

핵심은 "예산 초과를 FAILED 로 반드시 닫는다"(docs/str/03 "예산 초과는 LlmUnavailable") 가 유지되어
백엔드 1회 재시도가 409 에 영원히 막히지 않음(규약 6.3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.schemas.str import DraftRequest
from aml_ai.str.domain.request_hash import request_hash
from aml_ai.str.infrastructure.generation_repository import ClaimNew, GenerationRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.db


def _req(sample: dict) -> DraftRequest:
    return DraftRequest.model_validate(sample)


def _claim_and_fail_as_llm_unavailable(
    factory: sessionmaker[Session], req: DraftRequest, h: str, settings: Settings
) -> str:
    """draft_service.create() 의 except → _fail(code=LLM_UNAVAILABLE) 호출 모양을 그대로 재현."""
    with factory() as s:
        repo = GenerationRepository(s, settings)
        claim = repo.claim(req, h)
        assert isinstance(claim, ClaimNew)
        repo.fail(claim.generation_id, code=LlmUnavailable.code, message="draft budget exceeded")
        return claim.generation_id


def _reclaim(factory: sessionmaker[Session], req: DraftRequest, h: str, settings: Settings):
    with factory() as s:
        return GenerationRepository(s, settings).claim(req, h)


def test_preflight_llm_unavailable_closes_failed_and_retry_claims_new(
    db_session_factory: sessionmaker[Session],
    draft_request_sample: dict,
) -> None:
    """선체크 실패 → generations FAILED(LLM_UNAVAILABLE). 같은 요청 재진입은 ClaimNew(409 아님)."""
    get_settings.cache_clear()
    settings = get_settings()
    req = _req(draft_request_sample)
    h = request_hash(req)

    gid1 = _claim_and_fail_as_llm_unavailable(db_session_factory, req, h, settings)
    claim2 = _reclaim(db_session_factory, req, h, settings)
    assert isinstance(claim2, ClaimNew), f"FAILED 뒤 ClaimNew 여야 — 받은 것: {type(claim2).__name__}"
    assert claim2.generation_id != gid1

    with db_session_factory() as s:
        rows = s.execute(
            text("SELECT status, error FROM ai.generations WHERE draft_id=:d ORDER BY created_at"),
            {"d": req.draft_id},
        ).all()
    assert [r.status for r in rows] == ["FAILED", "PROCESSING"]
    assert "LLM_UNAVAILABLE" in (rows[0].error or "")
