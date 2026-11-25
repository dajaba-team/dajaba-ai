"""요약 조회·저장 마감 (11/25 전체 점검, docs/str/03)"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from aml_ai.shared.db import is_timeout
from aml_ai.shared.errors import LlmUnavailable


@contextmanager
def rollback_on_read_timeout(session: Session | None) -> Iterator[None]:
    try:
        yield
    except (LlmUnavailable, DBAPIError) as exc:
        if isinstance(exc, DBAPIError) and not is_timeout(exc):
            raise
        if session is not None:
            session.rollback()
        if isinstance(exc, LlmUnavailable):
            raise
        raise LlmUnavailable("summary deadline passed") from None


def remaining_before_save(deadline: float, now: float) -> float:
    remaining = deadline - now
    if remaining <= 0:
        raise LlmUnavailable("summary deadline passed before save")
    return remaining


def check_before_commit(deadline: float, now: float) -> None:
    if now > deadline:
        raise LlmUnavailable("summary deadline passed before commit")
