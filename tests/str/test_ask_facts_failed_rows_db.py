"""SCRUM-413 회귀 — facts 조회 실패 때 FAILED 감사 행은 develop 과 같음 (docs/str/03 질문 답변 2·10). 실제 PostgreSQL.

rollback 은 시간 초과(남은 ≤0·57014·55P03 → LlmUnavailable)에서만. 400 두 경우는 FAILED 행이 같은 값으로 남고,
시간 초과가 아닌 DB 오류(500)는 깨진 트랜잭션이라 FAILED 저장이 실패해 행이 없음(develop 그대로, 경고 로그만).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import InvalidRequest
from aml_ai.str.application.ask_service import AskService
from aml_ai.str.infrastructure.ask_llm import AskLlm
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.summary_repository import SummaryRepository
from aml_ai.str.infrastructure.transaction_reader import TransactionReader
from tests.str.ask_service_support import StubLlm, ask_request, plan_text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


class _FailingReader(TransactionReader):
    """진짜 bound_to_deadline + 읽기 트랜잭션을 연 뒤 경우별 실패."""

    def __init__(self, session: Session, mode: str) -> None:
        super().__init__(session)
        self.mode = mode

    def load_transactions(self, ids):  # type: ignore[no-untyped-def]
        self._s.execute(text("SELECT 1"))  # 실제 조회처럼 읽기 트랜잭션이 열린 상태
        if self.mode == "missing":
            raise InvalidRequest("missing transaction ids")
        if self.mode == "db500":
            self._s.execute(text("SELECT * FROM ops.scrum413_no_such_table"))  # 42P01 — 시간 초과 아님
        return []  # no_reportable — has_reportable False


def _service(session: Session, mode: str) -> AskService:
    s = get_settings()
    labels = load_display_labels()
    return AskService(
        settings=s,
        session=session,
        reader=_FailingReader(session, mode),
        llm=AskLlm(StubLlm([plan_text()]), s, labels=labels),
        repo=SummaryRepository(session),
        labels=labels,
    )


def _rows(session: Session) -> list[tuple[str, str | None]]:
    session.rollback()
    rows = session.execute(text("SELECT status, error FROM ai.generations WHERE kind='ASK'"))
    return [(r.status, r.error) for r in rows]


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("missing", "INVALID_REQUEST: missing transaction ids"),
        ("no_reportable", "INVALID_REQUEST: no reportable transactions"),
    ],
)
def test_400_keeps_failed_row_as_develop(db_session: Session, mode: str, error: str) -> None:
    with pytest.raises(InvalidRequest):
        _service(db_session, mode).ask(ask_request())
    assert _rows(db_session) == [("FAILED", error)]


def test_non_timeout_db_error_500_leaves_no_failed_row_as_develop(db_session: Session) -> None:
    """시간 초과가 아닌 DB 오류는 rollback 하지 않음 — develop 처럼 FAILED 저장이 깨진 트랜잭션에서 실패(행 없음)."""
    with pytest.raises(ProgrammingError):
        _service(db_session, "db500").ask(ask_request())
    assert _rows(db_session) == []
