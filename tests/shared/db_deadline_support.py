"""SCRUM-413 공용 — 가짜 세션·시계(연결·SQL·시계 읽기 순서를 한 목록에 남김). DB 0."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy.exc import OperationalError

SET_CONFIG = "set_config"


@dataclass
class Events:
    items: list[object] = field(default_factory=list)

    def sqls(self) -> list[str]:
        return [e[1] for e in self.items if isinstance(e, tuple) and e[0] == "sql"]

    def params(self) -> list[object]:
        return [e[2] for e in self.items if isinstance(e, tuple) and e[0] == "sql"]

    def index(self, name: str) -> int:
        return next(i for i, e in enumerate(self.items) if e == name)


class FakeClock:
    """부를 때마다 'clock' 을 남김. `jump_at`=n 이면 n 번째 읽기부터 `jump_to`."""

    def __init__(
        self, events: Events, now: float, *, jump_at: int | None = None, jump_to: float = 0.0
    ) -> None:
        self.events = events
        self.now = now
        self.reads = 0
        self.jump_at = jump_at
        self.jump_to = jump_to

    def __call__(self) -> float:
        self.reads += 1
        self.events.items.append("clock")
        if self.jump_at is not None and self.reads >= self.jump_at:
            return self.jump_to
        return self.now


class _Result:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return list(self._rows)

    def mappings(self) -> _Result:
        return self


class FakeSession:
    """connection()·begin_nested()·execute() 만. `rows_for` 의 낱말이 SQL 에 있으면 그 행을 돌려줌."""

    def __init__(self, events: Events, rows_for: dict[str, list[object]] | None = None) -> None:
        self.events = events
        self.rows_for = rows_for or {}

    def connection(self) -> object:
        self.events.items.append("connection")
        return object()

    @contextmanager
    def begin_nested(self) -> Iterator[None]:
        self.events.items.append("savepoint")
        yield

    def execute(self, stmt: object, params: object = None) -> _Result:
        sql = str(stmt)
        self.events.items.append(("sql", sql, params))
        for word, rows in self.rows_for.items():
            if word in sql:
                return _Result(rows)
        return _Result([])


class _Orig(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"sqlstate {sqlstate}")
        self.sqlstate = sqlstate


def db_error(sqlstate: str) -> OperationalError:
    """psycopg 예외처럼 `orig.sqlstate` 가 있는 DBAPIError."""
    return OperationalError("SELECT 1", {}, _Orig(sqlstate))
