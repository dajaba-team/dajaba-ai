"""SCRUM-57·91 — verify 저장 (-m db). docs/str/08 "DB" 층.

SCRUM-92 judge_* 5칸 왕복은 `test_verify_db_judge_meta.py`.

1) `VerificationRepository.save` 왕복 — `narrative_sha256`(검증 본문 해시, NOT NULL)·
   `request_id`(`current_request_id()` 값, "-" 면 null) 포함 모든 칸이 raw SELECT 로 그대로.
2) 없는 `generation_id` 로 `VerifyService.verify()` → `DraftNotFound`, 행 0.
3) **SCRUM-91** — `AI_LLM_MOCK=true` 로 `POST /v1/str/verify` → 200 `VERIFY_UNAVAILABLE`·행 1.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from aml_ai.shared.config import get_settings
from aml_ai.shared.db import get_session
from aml_ai.shared.errors import DraftNotFound
from aml_ai.shared.schemas.str import (
    RevisedNarrativeSection,
    SectionV1,
    VerifyRequest,
    VerifyStatus,
)
from aml_ai.str.application.verify_service import VerifyService
from aml_ai.str.infrastructure.verification_repository import VerificationRepository
from tests.str.integration_support import INTEGRATION_INTERNAL_KEY
from tests.str.verify_db_support import (
    SAMPLE_CODE_CHECKS,
    SAMPLE_LLM_CHECKS,
    SAMPLE_SHA,
    assert_judge_meta_null,
    read_run,
    save_code_failed,
    seed_draft,
)

pytestmark = pytest.mark.db


@pytest.mark.parametrize("request_id", ["req-abcde-123", None])
def test_save_round_trip(db_session: Session, _db_engine: Engine, request_id: str | None) -> None:
    """repo.save 가 모든 칸을 그대로 저장 — request_id None(nullable), judge_meta None 도."""
    repo = VerificationRepository(db_session)
    vid = save_code_failed(repo, request_id=request_id, judge_meta=None)

    row = read_run(_db_engine, vid)
    assert row.verification_id == vid
    assert row.generation_id == "g" * 32
    assert row.draft_id == "draft-57"
    assert row.revision_no == 2
    assert row.code_checks == [c.model_dump(mode="json") for c in SAMPLE_CODE_CHECKS]
    assert row.llm_checks == [c.model_dump(mode="json") for c in SAMPLE_LLM_CHECKS]
    assert row.passed is False
    assert row.status == VerifyStatus.CODE_FAILED.value
    assert row.verifier_version == "judge_v1@test"
    assert row.narrative_sha256 == SAMPLE_SHA
    assert row.request_id == request_id
    assert_judge_meta_null(row)  # SCRUM-92 — judge_* 5칸 전부 NULL
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


# ── SCRUM-91 — verify API 끝까지 돎(평가자 못 부름 → 200 VERIFY_UNAVAILABLE) ──


@pytest.fixture
def _verify_client(db_session: Session, _ai_mock_env) -> Iterator[TestClient]:
    """SCRUM-91 — AI_LLM_MOCK=true 로 verify API 호출. ops_seed 없이(verify 는 ops 안 읽음)."""
    from aml_ai.main import app

    get_settings.cache_clear()
    app.dependency_overrides[get_session] = lambda: db_session
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_verify_api_returns_unavailable_without_recording(
    db_session: Session,
    _db_engine: Engine,
    _verify_client: TestClient,
    draft_request_sample: dict,
    draft_response_sample: dict,
) -> None:
    """SCRUM-91 — judge 녹화 없음 → 200 VERIFY_UNAVAILABLE, verification_runs 1행."""
    gid = seed_draft(db_session, draft_request_sample, draft_response_sample)
    # 요청 narrative 는 응답과 같은 세트 — 코드 검사 통과해야 judge 호출로 떨어진다
    req = {
        "generation_id": gid,
        "revision_no": 1,
        "narrative": draft_response_sample["narrative"],
    }

    resp = _verify_client.post(
        "/v1/str/verify", json=req, headers={"X-Internal-Key": INTEGRATION_INTERNAL_KEY}
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == VerifyStatus.VERIFY_UNAVAILABLE.value
    assert data["passed"] is False
    assert data["llm_checks"] is None

    with _db_engine.begin() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM ai.verification_runs WHERE generation_id = :g"), {"g": gid}
        ).scalar_one()
    assert n == 1
