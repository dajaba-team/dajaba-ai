"""`shared.db.end_read` 단위 (SCRUM-122).

규칙: "LLM 호출 바로 앞에는 반드시 `end_read`, `end_read` 와 LLM 호출 사이에는 DB 읽기 금지" (docs/str/03).
`end_read(session)` 자체는:
- `session.in_transaction()` 이 False 면 no-op (이미 닫힌 상태에 또 커밋 금지)
- `session.new/dirty/deleted` 중 하나라도 있으면 **명시적 `raise RuntimeError`** (`python -O` 안전 — assert 안 씀)
- 정상 읽기 뒤 `session.commit()` 1회 호출

`expire_on_commit=False` 전제라 commit 뒤 ORM 객체 접근은 가능 — 그 라운드는 DB 가 필요한
`test_transaction_boundaries.py` 에서 (여기서는 MagicMock 으로 상태만 본다).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aml_ai.shared.db import end_read


def test_end_read_no_transaction_is_noop() -> None:
    """`in_transaction()=False` → commit 호출 없음, 예외 없음."""
    session = MagicMock()
    session.in_transaction.return_value = False
    end_read(session)
    session.commit.assert_not_called()


@pytest.mark.parametrize("dirty_attr", ["new", "dirty", "deleted"])
def test_end_read_rejects_pending_writes_with_runtime_error(dirty_attr: str) -> None:
    """읽기만 한 트랜잭션 가드 — new/dirty/deleted 있으면 RuntimeError (assert 아님)."""
    session = MagicMock()
    session.in_transaction.return_value = True
    # new/dirty/deleted 는 Session 에서 "truthy iterable" — set() 로 모양만 흉내
    for attr in ("new", "dirty", "deleted"):
        setattr(session, attr, set() if attr != dirty_attr else {object()})
    with pytest.raises(RuntimeError):
        end_read(session)
    session.commit.assert_not_called()


def test_end_read_commits_clean_read_transaction() -> None:
    """정상 — in_transaction=True + new/dirty/deleted 비어 있음 → commit 1회."""
    session = MagicMock()
    session.in_transaction.return_value = True
    session.new = set()
    session.dirty = set()
    session.deleted = set()
    end_read(session)
    session.commit.assert_called_once_with()


def test_end_read_never_calls_rollback() -> None:
    """rollback 쓰면 ORM 객체 만료 → 다음 접근에서 연결 재취득. 그 경로 금지."""
    session = MagicMock()
    session.in_transaction.return_value = True
    session.new = set()
    session.dirty = set()
    session.deleted = set()
    end_read(session)
    session.rollback.assert_not_called()
