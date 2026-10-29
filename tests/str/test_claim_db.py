"""str/08 "DB" 층 — draft_id 선점 ①~④ + SUCCEEDED 반환 전 해시 재확인.

⑤(STALE 뒤 늦은 finish)는 펜싱이라 test_fencing_db.py 로 분리.

지금은 뼈대 — claim/ClaimNew/ClaimReuse/request_hash 는 Codex 구현 뒤 통과한다.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from aml_ai.shared.errors import GenerationInProgress, InvalidRequest
from aml_ai.shared.schemas.str import DraftRequest, DraftResponse
from aml_ai.str.domain.request_hash import request_hash
from aml_ai.str.infrastructure.generation_repository import (
    ClaimNew,
    ClaimReuse,
    GenerationRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

pytestmark = pytest.mark.db


def _req(sample: dict, **overrides: object) -> DraftRequest:
    body = {**sample, **overrides}
    return DraftRequest.model_validate(body)


def test_claim_first_insert(db_session: Session, draft_request_sample: dict) -> None:
    """처음 들어온 draft_id → PROCESSING 1행, ClaimNew 로 generation_id 돌려받는다."""
    req = _req(draft_request_sample)
    result = GenerationRepository(db_session).claim(req, request_hash(req))
    assert isinstance(result, ClaimNew)
    row = db_session.execute(
        text("SELECT status, request_hash FROM ai.generations WHERE draft_id=:d"),
        {"d": req.draft_id},
    ).one()
    assert row.status == "PROCESSING"
    assert row.request_hash == request_hash(req)


def test_claim_concurrent_same_request_one_wins(
    db_session_factory: sessionmaker[Session], draft_request_sample: dict
) -> None:
    """① 같은 draft_id · 같은 해시 동시 2건 → 하나는 ClaimNew, 다른 하나는 409 GENERATION_IN_PROGRESS."""
    req = _req(draft_request_sample)
    h = request_hash(req)

    def _run() -> object:
        with db_session_factory() as s:
            try:
                return GenerationRepository(s).claim(req, h)
            except GenerationInProgress as exc:
                return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result() for f in [pool.submit(_run), pool.submit(_run)]]

    news = [r for r in results if isinstance(r, ClaimNew)]
    inprogress = [r for r in results if isinstance(r, GenerationInProgress)]
    assert len(news) == 1 and len(inprogress) == 1


def test_claim_after_failed_same_request_gets_new_id(db_session: Session, draft_request_sample: dict) -> None:
    """② FAILED 뒤 같은 요청 → 새 generation_id, 옛 FAILED 행은 그대로 남는다."""
    req = _req(draft_request_sample)
    h = request_hash(req)
    repo = GenerationRepository(db_session)
    first = repo.claim(req, h)
    assert isinstance(first, ClaimNew)
    repo.fail(first.generation_id, code="INTERNAL", message="boom")

    second = repo.claim(req, h)
    assert isinstance(second, ClaimNew)
    assert second.generation_id != first.generation_id

    rows = db_session.execute(
        text("SELECT generation_id, status, error FROM ai.generations WHERE draft_id=:d ORDER BY created_at"),
        {"d": req.draft_id},
    ).all()
    assert [r.status for r in rows] == ["FAILED", "PROCESSING"]
    assert rows[0].error is not None  # 옛 FAILED 행 그대로


def test_claim_concurrent_different_hashes_second_gets_400(
    db_session_factory: sessionmaker[Session], draft_request_sample: dict
) -> None:
    """③ 내용이 다른 두 요청 동시 → 다른 쪽 400. 결과 받지도, 새로 생성도 안 함."""
    req_a = _req(draft_request_sample)
    sample_b = {**draft_request_sample, "case_no": draft_request_sample["case_no"] + "-x"}
    req_b = _req(sample_b)
    assert req_a.draft_id == req_b.draft_id
    assert request_hash(req_a) != request_hash(req_b)

    def _run(req: DraftRequest) -> object:
        with db_session_factory() as s:
            try:
                return GenerationRepository(s).claim(req, request_hash(req))
            except (GenerationInProgress, InvalidRequest) as exc:
                return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [f.result() for f in [pool.submit(_run, req_a), pool.submit(_run, req_b)]]

    bads = [r for r in results if isinstance(r, InvalidRequest)]
    assert len(bads) == 1, f"다른 쪽은 400 이어야 한다. 받은 것: {results}"


def test_claim_stale_processing_recovers(db_session: Session, draft_request_sample: dict) -> None:
    """④ STALE_PROCESSING_S 지난 PROCESSING → FAILED(STALE_PROCESSING) 로 닫히고 재시도가 성공."""
    req = _req(draft_request_sample)
    h = request_hash(req)
    old_ts = datetime.utcnow() - timedelta(seconds=200)
    db_session.execute(
        text("""
            INSERT INTO ai.generations
                (generation_id, kind, draft_id, request, request_hash, status, created_at)
            VALUES (:gid, 'DRAFT', :d, :req, :h, 'PROCESSING', :ts)
        """),
        {"gid": "dead" + "0" * 28, "d": req.draft_id, "req": "{}", "h": h, "ts": old_ts},
    )
    db_session.commit()

    result = GenerationRepository(db_session).claim(req, h)
    assert isinstance(result, ClaimNew)
    rows = db_session.execute(
        text("SELECT status, error FROM ai.generations WHERE draft_id=:d ORDER BY created_at"),
        {"d": req.draft_id},
    ).all()
    assert [r.status for r in rows] == ["FAILED", "PROCESSING"]
    assert "STALE_PROCESSING" in (rows[0].error or "")


def test_claim_succeeded_reuses_response(
    db_session: Session, draft_request_sample: dict, draft_response_sample: dict
) -> None:
    """SUCCEEDED 뒤 같은 요청 → ClaimReuse(저장된 DraftResponse). LLM 호출 없음."""
    req = _req(draft_request_sample)
    h = request_hash(req)
    # 스키마에 맞는 전체 DraftResponse 저장 — _reuse 가 model_validate 로 복원
    stored = {**draft_response_sample, "draft_id": req.draft_id, "generation_id": "aa" + "0" * 30}
    DraftResponse.model_validate(stored)  # 저장 전 자가 검증 — 테스트가 silently 뚫리지 않게
    db_session.execute(
        text(
            """
            INSERT INTO ai.generations
                (generation_id, kind, draft_id, request, request_hash, response, status)
            VALUES (:gid, 'DRAFT', :d, '{}', :h, CAST(:resp AS JSONB), 'SUCCEEDED')
            """
        ),
        {"gid": stored["generation_id"], "d": req.draft_id, "h": h, "resp": json.dumps(stored)},
    )
    db_session.commit()

    result = GenerationRepository(db_session).claim(req, h)
    assert isinstance(result, ClaimReuse)
    assert result.response.draft_id == req.draft_id
    assert result.response.generation_id == stored["generation_id"]
    assert len(result.response.narrative) == 6  # 섹션 6개 전부 복원


def test_claim_hash_recheck_before_reuse(db_session: Session, draft_request_sample: dict) -> None:
    """SUCCEEDED 분기 반환 전 해시 재확인 — DB 의 해시가 지금 요청 해시와 다르면 400 (0단계 비교 뒤 레이스 방어)."""
    req = _req(draft_request_sample)
    db_session.execute(
        text("""
            INSERT INTO ai.generations
                (generation_id, kind, draft_id, request, request_hash, response, status)
            VALUES (:gid, 'DRAFT', :d, '{}', :h, '{}', 'SUCCEEDED')
        """),
        {"gid": "bb" + "0" * 30, "d": req.draft_id, "h": "deadbeef" * 8},
    )
    db_session.commit()

    with pytest.raises(InvalidRequest):
        GenerationRepository(db_session).claim(req, request_hash(req))
