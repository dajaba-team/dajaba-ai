"""SCRUM-413 질문 답변 facts 조회 시간 제한 — 실제 PostgreSQL (docs/str/03 질문 답변 2).

조회 대신 `pg_sleep` 을 돌리는 reader 로 남은 시간(0.3초) 근처에서 끊기고 502, 같은 세션으로 FAILED 저장.
성공 뒤 `statement_timeout`·`lock_timeout` 은 원래 값(트랜잭션 한정).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import LlmUnavailable
from aml_ai.str.application.ask_service import AskService
from aml_ai.str.infrastructure.ask_llm import AskLlm
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.summary_repository import SummaryRepository
from aml_ai.str.infrastructure.transaction_reader import TransactionReader
from tests.str.ask_service_support import StubLlm, ask_request, plan_text
from tests.str.summary_service_support import StubReader

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db
LIMIT_S = 0.3
SLACK_S = 2.0  # 컨테이너 왕복·rollback 여유


class _SleepReader(TransactionReader):
    """진짜 bound_to_deadline(같은 세션) + 조회 자리에 pg_sleep(5)."""

    def load_transactions(self, ids):  # type: ignore[no-untyped-def]
        self._s.execute(text("SELECT pg_sleep(5)"))
        raise AssertionError("pg_sleep 이 끊기지 않음")


class _NoSqlReader(TransactionReader):
    """진짜 bound_to_deadline + 조회 결과는 StubReader 숫자(ops 표 없이)."""

    def load_transactions(self, ids):  # type: ignore[no-untyped-def]
        return StubReader().load_transactions(ids)

    def load_subject(self, alert, txs):  # type: ignore[no-untyped-def]
        return StubReader().load_subject(alert, txs)


class _LateClock:
    """첫 읽기(요청 시작 deadline)는 지금, 그 뒤 읽기는 `skip_s` 앞으로 — 조회 직전 남은 시간이 LIMIT_S."""

    def __init__(self, skip_s: float) -> None:
        self.skip_s = skip_s
        self.reads = 0

    def __call__(self) -> float:
        self.reads += 1
        return time.monotonic() + (0.0 if self.reads == 1 else self.skip_s)


def _service(session: Session, reader: TransactionReader, llm: StubLlm, *, late: bool = False) -> AskService:
    s = get_settings()
    clock = _LateClock(s.ask_budget_s - LIMIT_S) if late else time.monotonic
    labels = load_display_labels()
    return AskService(
        settings=s,
        session=session,
        reader=reader,
        llm=AskLlm(llm, s, clock=clock, labels=labels),
        repo=SummaryRepository(session),
        labels=labels,
        clock=clock,
    )


def _rows(session: Session) -> list[tuple[str, str | None]]:
    rows = session.execute(text("SELECT status, error FROM ai.generations WHERE kind='ASK'"))
    return [(r.status, r.error) for r in rows]


def test_slow_facts_query_is_cut_near_remaining_and_failed_row_saved(db_session: Session) -> None:
    llm = StubLlm([plan_text()])
    svc = _service(db_session, _SleepReader(db_session), llm, late=True)
    start = time.monotonic()
    with pytest.raises(LlmUnavailable):
        svc.ask(ask_request())
    assert time.monotonic() - start < LIMIT_S + SLACK_S
    assert llm.calls == []
    ((status, error),) = _rows(db_session)
    assert status == "FAILED" and error.startswith("LLM_UNAVAILABLE: ")


def test_timeouts_are_released_after_successful_ask(db_session: Session) -> None:
    svc = _service(db_session, _NoSqlReader(db_session), StubLlm([plan_text()]))
    svc.ask(ask_request())
    assert db_session.execute(text("SHOW statement_timeout")).scalar() == "0"
    assert db_session.execute(text("SHOW lock_timeout")).scalar() == "0"
    assert [s for s, _ in _rows(db_session)] == ["SUCCEEDED"]


def test_reader_bound_sets_timeout_inside_transaction_only(db_session: Session) -> None:
    TransactionReader(db_session).bound_to_deadline(time.monotonic() + 5.0, time.monotonic)
    inside = db_session.execute(text("SHOW statement_timeout")).scalar()
    assert inside != "0" and db_session.execute(text("SHOW lock_timeout")).scalar() == inside
    db_session.commit()
    assert db_session.execute(text("SHOW statement_timeout")).scalar() == "0"
