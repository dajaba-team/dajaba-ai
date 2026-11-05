"""SCRUM-92·144 — `verification_runs.judge_*` 5칸 저장 왕복 (-m db).

docs/shared/03 verification_runs 표 (SCRUM-92 추가), docs/str/06 평가자 "모델·토큰 기록".
SCRUM-144: 2차 complete_json 예외 시 1차 토큰이 DB 에 남는지 서비스 전 흐름으로 확인.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.schemas.str import (
    JudgeMeta,
    RevisedNarrativeSection,
    SectionV1,
    VerifyRequest,
    VerifyStatus,
)
from aml_ai.str.application.verify_service import VerifyService
from aml_ai.str.infrastructure.generation_repository import GenerationRepository
from aml_ai.str.infrastructure.verification_repository import VerificationRepository
from tests.str.judge_support import StubCall, StubLlm, make_judge
from tests.str.verify_db_support import read_judge_meta, save_passed_with_meta, seed_draft

pytestmark = pytest.mark.db


def test_save_round_trip_with_judge_meta(db_session: Session, _db_engine: Engine) -> None:
    """SCRUM-92 — judge_meta 를 넣으면 judge_* 5칸이 그대로 저장."""
    repo = VerificationRepository(db_session)
    meta = JudgeMeta(
        llm_model="gpt-5-judge-sol",
        prompt_version="judge_v1",
        tokens_in=1842,
        tokens_out=612,
        latency_ms=8450,
        attempts=2,
    )
    vid = save_passed_with_meta(repo, judge_meta=meta)

    row = read_judge_meta(_db_engine, vid)
    assert row.judge_llm_model == "gpt-5-judge-sol"
    assert row.judge_tokens_in == 1842
    assert row.judge_tokens_out == 612
    assert row.judge_latency_ms == 8450
    assert row.judge_attempts == 2


def _stub_1st_schema_then_unavailable() -> StubLlm:
    """1차 "not-json"(1200/300/3000ms, model=gpt-6.1-terra), 2차 LlmUnavailable."""
    return StubLlm(
        call_specs=[
            StubCall(
                text="not-json",
                model="gpt-6.1-terra",
                tokens_in=1200,
                tokens_out=300,
                latency_ms=3000,
            ),
            StubCall(text="unused", exc=LlmUnavailable("timeout")),
        ]
    )


def _build_verify_service_with_stub(db_session: Session, stub: StubLlm) -> VerifyService:
    judge = make_judge(stub, prompt_name="judge_v2", request_sections=[s.value for s in SectionV1])
    return VerifyService(
        settings=get_settings(),
        session=db_session,
        generations=GenerationRepository(db_session),
        verifications=VerificationRepository(db_session),
        judge=judge,
    )


def _read_run(engine: Engine, gid: str) -> object:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT status, judge_llm_model, judge_tokens_in, judge_tokens_out, "
                "judge_latency_ms, judge_attempts "
                "FROM ai.verification_runs WHERE generation_id = :g"
            ),
            {"g": gid},
        ).one()


def test_verify_2nd_judge_call_exception_persists_1st_meta_to_db(
    db_session: Session,
    _db_engine: Engine,
    draft_request_sample: dict,
    draft_response_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SCRUM-144 — 실 DB + 실 `Judge` + `StubLlm` 로 2차 `complete_json` 예외 재현.

    status `VERIFY_UNAVAILABLE`, `judge_*` 5칸에 1차 토큰·모델·`attempts=2` 가 남는다.
    develop 에서는 try 밖 예외라 `judge_*` NULL 로 fail.
    """
    monkeypatch.setenv("AI_LLM_MOCK", "true")
    monkeypatch.setenv("RAG_ENABLED", "false")
    get_settings.cache_clear()

    gid = seed_draft(db_session, draft_request_sample, draft_response_sample)
    stub = _stub_1st_schema_then_unavailable()
    svc = _build_verify_service_with_stub(db_session, stub)
    narrative = [RevisedNarrativeSection.model_validate(s) for s in draft_response_sample["narrative"]]
    resp = svc.verify(VerifyRequest(generation_id=gid, revision_no=1, narrative=narrative))

    assert resp.status is VerifyStatus.VERIFY_UNAVAILABLE
    assert resp.judge_meta is None, "응답은 SCRUM-92 규칙 — VERIFY_UNAVAILABLE 이면 null"
    row = _read_run(_db_engine, gid)
    assert row.status == VerifyStatus.VERIFY_UNAVAILABLE.value
    assert row.judge_attempts == 2
    assert row.judge_tokens_in == 1200
    assert row.judge_tokens_out == 300
    assert row.judge_latency_ms == 3000
    assert row.judge_llm_model == "gpt-6.1-terra"
    assert len(stub.calls) == 2
