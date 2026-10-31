"""SCRUM-57 — verify 저장 2가지 (-m db). docs/str/08 "DB" 층.

1) `VerificationRepository.save` 왕복 — `narrative_sha256`(검증 본문 해시, NOT NULL)·
   `request_id`(current_request_id() 값, "-" 면 null) 포함 모든 칸이 raw SELECT 로 그대로.
   `request_id=None` 케이스 포함(nullable 확인).
2) 없는 `generation_id` 로 `VerifyService.verify()` → `DraftNotFound`, `verification_runs` 행 0.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import DraftNotFound
from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheck,
    CodeCheckName,
    LlmCheck,
    LlmCheckName,
    RevisedNarrativeSection,
    SectionV1,
    VerifyRequest,
    VerifyStatus,
)
from aml_ai.str.application.verify_service import VerifyService
from aml_ai.str.infrastructure.verification_repository import VerificationRepository

pytestmark = pytest.mark.db

_CODE_CHECKS = [
    CodeCheck(
        check=CodeCheckName.EVIDENCE_IN_SCOPE,
        section=None,
        draft_value="draft-X",
        source_value=None,
        match=False,
        reason=CheckReason.OUT_OF_SCOPE,
    ),
]
_LLM_CHECKS = [
    LlmCheck(check=LlmCheckName.FIVE_W_ONE_H_COMPLETE, comment="섹션 다 있음", score=5),
]
_SHA = "a" * 64


@pytest.mark.parametrize("request_id", ["req-abcde-123", None])
def test_save_round_trip(db_session: Session, _db_engine: Engine, request_id: str | None) -> None:
    """repo.save 가 모든 칸을 그대로 저장 — request_id None(nullable) 도."""
    repo = VerificationRepository(db_session)
    vid = repo.save(
        generation_id="g" * 32,
        draft_id="draft-57",
        revision_no=2,
        code_checks=_CODE_CHECKS,
        llm_checks=_LLM_CHECKS,
        passed=False,
        status=VerifyStatus.CODE_FAILED,
        verifier_version="judge_v1@test",
        narrative_sha256=_SHA,
        request_id=request_id,
    )
    with _db_engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT verification_id, generation_id, draft_id, revision_no, "
                "code_checks, llm_checks, passed, status, verifier_version, "
                "narrative_sha256, request_id, created_at "
                "FROM ai.verification_runs WHERE verification_id = :v"
            ),
            {"v": vid},
        ).one()
    assert row.verification_id == vid
    assert row.generation_id == "g" * 32
    assert row.draft_id == "draft-57"
    assert row.revision_no == 2
    assert row.code_checks == [c.model_dump(mode="json") for c in _CODE_CHECKS]
    assert row.llm_checks == [c.model_dump(mode="json") for c in _LLM_CHECKS]
    assert row.passed is False
    assert row.status == VerifyStatus.CODE_FAILED.value
    assert row.verifier_version == "judge_v1@test"
    assert row.narrative_sha256 == _SHA
    assert row.request_id == request_id
    assert row.created_at is not None


def test_verify_404_leaves_no_row(
    db_session: Session,
    _db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """없는 generation_id → DraftNotFound, verification_runs 행 0."""
    monkeypatch.setenv("AI_LLM_MOCK", "true")
    monkeypatch.setenv("RAG_ENABLED", "false")
    get_settings.cache_clear()

    service = VerifyService.build(db_session, get_settings())
    narrative = [RevisedNarrativeSection(section=s, text="x", cites=[], evidence_ids=[]) for s in SectionV1]
    req = VerifyRequest(generation_id="missing" + "0" * 25, revision_no=1, narrative=narrative)

    with pytest.raises(DraftNotFound):
        service.verify(req)

    with _db_engine.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM ai.verification_runs")).scalar_one()
    assert n == 0
