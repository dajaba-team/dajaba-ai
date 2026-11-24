"""SCRUM-413 `shared.db.bound_to_deadline`·`is_timeout` — 가짜 세션·시계 (docs/str/03 질문 답변 2 · 초안 6). DB 0."""

from __future__ import annotations

import pytest

from aml_ai.shared.db import TIMEOUT_SQLSTATES, bound_to_deadline, is_timeout
from tests.shared.db_deadline_support import SET_CONFIG, Events, FakeClock, FakeSession, db_error


class _Expired(Exception):
    pass


def _bound(session: FakeSession, deadline: float, clock: FakeClock) -> None:
    bound_to_deadline(session, deadline, clock, lambda: _Expired("deadline"))


def test_sets_both_timeouts_to_remaining_ms_transaction_local() -> None:
    ev = Events()
    _bound(FakeSession(ev), 100.3, FakeClock(ev, 100.0))
    (sql,) = ev.sqls()
    assert "set_config('statement_timeout'" in sql and "set_config('lock_timeout'" in sql
    assert sql.count(", true)") == 2  # 트랜잭션 한정(SET LOCAL 과 같음)
    assert list(ev.params()[0].values()) == ["300ms"]  # 값은 바인드 파라미터


def test_counts_remaining_after_connection_is_taken() -> None:
    """풀 대기 뒤에 셈(★A ② (가)) — 연결을 얻은 다음 시계를 읽는다."""
    ev = Events()
    _bound(FakeSession(ev), 100.3, FakeClock(ev, 100.0))
    assert ev.index("connection") < ev.index("clock")


@pytest.mark.parametrize("now", [100.3, 100.31, 200.0])
def test_expired_after_connection_runs_no_sql(now: float) -> None:
    ev = Events()
    with pytest.raises(_Expired):
        _bound(FakeSession(ev), 100.3, FakeClock(ev, now))
    assert ev.sqls() == []


def test_expired_during_set_round_trip_raises_after_set() -> None:
    """설정 왕복 뒤 다시 확인 — 지났으면 그 뒤 조회를 시작하지 않게 raise."""
    ev = Events()
    clock = FakeClock(ev, 100.0, jump_at=2, jump_to=100.5)
    with pytest.raises(_Expired):
        _bound(FakeSession(ev), 100.3, clock)
    assert len(ev.sqls()) == 1 and SET_CONFIG in ev.sqls()[0]
    assert clock.reads >= 2


def test_tiny_remaining_floors_to_1ms() -> None:
    ev = Events()
    _bound(FakeSession(ev), 100.0004, FakeClock(ev, 100.0))
    assert list(ev.params()[0].values()) == ["1ms"]


def test_timeout_sqlstates_are_query_canceled_and_lock_not_available() -> None:
    assert TIMEOUT_SQLSTATES == ("57014", "55P03")


@pytest.mark.parametrize(
    ("sqlstate", "expected"), [("57014", True), ("55P03", True), ("08006", False), ("23505", False)]
)
def test_is_timeout_by_sqlstate(sqlstate: str, expected: bool) -> None:
    assert is_timeout(db_error(sqlstate)) is expected


def test_is_timeout_without_sqlstate_is_false() -> None:
    from sqlalchemy.exc import OperationalError

    assert is_timeout(OperationalError("SELECT 1", {}, Exception("no sqlstate"))) is False
