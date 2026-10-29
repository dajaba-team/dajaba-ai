"""str/08 "DB" 층 — 선점 ⑤ 펜싱.

finish/fail 은 WHERE generation_id=$1 AND status='PROCESSING'. STALE 로 이미 FAILED 된 행에
걸면 0행이 바뀌고, 호출자는 그 신호로 결과를 버린다(shared/03).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from aml_ai.shared.errors import FencedOut
from aml_ai.shared.schemas.str import DraftRequest, Facts
from aml_ai.str.domain.request_hash import request_hash
from aml_ai.str.infrastructure.generation_repository import ClaimNew, GenerationRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


def _req(sample: dict) -> DraftRequest:
    return DraftRequest.model_validate(sample)


def test_finish_fences_on_stale(db_session: Session, draft_request_sample: dict, mixed: Facts) -> None:
    """늦게 돌아온 옛 작업의 finish — WHERE status='PROCESSING' 이 0행이면 결과 버리고 FencedOut."""
    req = _req(draft_request_sample)
    repo = GenerationRepository(db_session)
    claim = repo.claim(req, request_hash(req))
    assert isinstance(claim, ClaimNew)
    gid = claim.generation_id

    # 밖에서 STALE 처리 — 다른 리더가 110초 뒤 PROCESSING 을 FAILED 로 닫음
    db_session.execute(
        text("UPDATE ai.generations SET status='FAILED', error='STALE_PROCESSING' WHERE generation_id=:g"),
        {"g": gid},
    )
    db_session.commit()

    # 늦게 돌아온 옛 시도의 finish → 0행 → FencedOut
    stored_response = {
        "draft_id": req.draft_id,
        "generation_id": gid,
        "facts": mixed.model_dump(mode="json"),
        "narrative": [],
        "generation_meta": {},
        "verification": None,
    }
    with pytest.raises(FencedOut):
        repo.finish(gid, facts=mixed, response_payload=stored_response, meta={})

    row = db_session.execute(
        text("SELECT status, error, response FROM ai.generations WHERE generation_id=:g"),
        {"g": gid},
    ).one()
    assert row.status == "FAILED"
    assert row.error == "STALE_PROCESSING"
    assert row.response is None  # finish 가 결과를 저장하지 못함


def test_fail_also_fences(db_session: Session, draft_request_sample: dict) -> None:
    """fail 도 같은 조건 — STALE 로 이미 닫힌 행을 다시 FAILED 로 덮어쓰지 않는다."""
    req = _req(draft_request_sample)
    repo = GenerationRepository(db_session)
    claim = repo.claim(req, request_hash(req))
    assert isinstance(claim, ClaimNew)
    gid = claim.generation_id

    db_session.execute(
        text("UPDATE ai.generations SET status='FAILED', error='STALE_PROCESSING' WHERE generation_id=:g"),
        {"g": gid},
    )
    db_session.commit()

    with pytest.raises(FencedOut):
        repo.fail(gid, code="LLM_UNAVAILABLE", message="late")

    row = db_session.execute(
        text("SELECT status, error FROM ai.generations WHERE generation_id=:g"),
        {"g": gid},
    ).one()
    assert row.error == "STALE_PROCESSING"  # 안 바뀜
