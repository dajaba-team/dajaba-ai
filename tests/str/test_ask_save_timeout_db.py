"""질문 답변 성공 저장 시간 제한 — 실제 PostgreSQL (SCRUM-290 2/2 추가 검토 1, docs/str/03 10단계).

다른 연결이 `ai.generations` 를 잠근 동안 남은 시간으로 묶은 저장은 그 시간 근처에서 `LlmUnavailable`,
트랜잭션은 rollback 되어 같은 세션으로 FAILED 를 남길 수 있다. 시간 제한 없는 저장(요약)은 그대로.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from aml_ai.shared.errors import LlmUnavailable
from aml_ai.str.infrastructure.summary_repository import SummaryRepository

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db
LIMIT_S = 0.3
SLACK_S = 2.0  # 컨테이너 왕복·rollback 여유


def _save(repo: SummaryRepository, gid: str, status: str = "SUCCEEDED", **kw) -> None:
    repo.save(
        generation_id=gid,
        case_no="CASE-ASK-SAVE",
        request={},
        facts=None,
        response_payload={},
        meta={},
        status=status,
        kind="ASK",
        **kw,
    )


def _statuses(session: Session) -> list[str]:
    rows = session.execute(text("SELECT status FROM ai.generations WHERE case_no='CASE-ASK-SAVE'"))
    return sorted(r.status for r in rows)


def test_locked_table_save_times_out_then_failed_row_saves(db_session: Session, _db_engine: Engine) -> None:
    repo = SummaryRepository(db_session)
    with _db_engine.connect() as holder:
        holder.execute(text("LOCK TABLE ai.generations IN ACCESS EXCLUSIVE MODE"))
        start = time.monotonic()
        with pytest.raises(LlmUnavailable):
            _save(repo, "g-locked01", timeout_s=LIMIT_S)
        assert time.monotonic() - start < LIMIT_S + SLACK_S
        holder.rollback()
    _save(repo, "g-locked02", status="FAILED")  # 같은 세션 — rollback 돼서 쓸 수 있음
    assert _statuses(db_session) == ["FAILED"]


def test_before_commit_hook_raising_rolls_back(db_session: Session) -> None:
    def late() -> None:
        raise LlmUnavailable("ask deadline passed")

    repo = SummaryRepository(db_session)
    with pytest.raises(LlmUnavailable):
        _save(repo, "g-late0001", timeout_s=5.0, before_commit=late)
    assert _statuses(db_session) == []


def test_timeout_is_transaction_local(db_session: Session) -> None:
    repo = SummaryRepository(db_session)
    _save(repo, "g-ok000001", timeout_s=5.0)
    assert db_session.execute(text("SHOW statement_timeout")).scalar() == "0"
    assert db_session.execute(text("SHOW lock_timeout")).scalar() == "0"
    assert _statuses(db_session) == ["SUCCEEDED"]
