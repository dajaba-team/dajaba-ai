"""SCRUM-92 — `verification_runs.judge_*` 5칸 저장 왕복 (-m db).

docs/shared/03 verification_runs 표 (SCRUM-92 추가), docs/str/06 평가자 "모델·토큰 기록".
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from aml_ai.shared.schemas.str import JudgeMeta
from aml_ai.str.infrastructure.verification_repository import VerificationRepository
from tests.str.verify_db_support import read_judge_meta, save_passed_with_meta

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
