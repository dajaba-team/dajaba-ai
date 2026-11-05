"""SQLAlchemy 2 (동기, psycopg). 계정 app_ai — ops 읽기, ai 쓰기. 세션은 요청 단위."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from aml_ai.shared.config import Settings, get_settings


class Base(DeclarativeBase):
    """ai 스키마 ORM 의 부모. 테이블 정의는 각 기능의 infrastructure/orm.py (docs/shared/03)."""


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    return create_engine(s.sqlalchemy_url, pool_pre_ping=True, pool_size=5, max_overflow=5, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI Depends 용."""
    factory = sessionmaker(bind=get_engine(), expire_on_commit=False)
    with factory() as session:
        yield session


def ping(settings: Settings) -> str:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 — health 는 이유를 한 단어로만
        return f"down:{type(exc).__name__}"


def end_read(session: Session) -> None:
    """읽기만 한 트랜잭션을 `commit()` 으로 닫아 연결을 풀로 돌려준다 (SCRUM-122, docs/str/03).

    규칙: "LLM 호출 바로 앞에는 반드시 `end_read`, `end_read` 와 LLM 호출 사이에는 DB 읽기 금지."
    `expire_on_commit=False` 전제라 commit 뒤 읽어 둔 ORM 값(txs·subject·StoredDraft)은 그대로 유효.

    - `in_transaction()=False` → no-op (이미 닫힌 세션에 또 commit 금지).
    - `new/dirty/deleted` 중 하나라도 있으면 **`raise RuntimeError`** (쓰기 가드 — 읽기 외 상태를
      실수로 날리지 않게. `assert` 안 씀 — `python -O` 에서 빠지면 조용히 통과하기 때문).
    - 정상이면 `session.commit()`. `rollback()` 쓰면 ORM 객체가 만료돼 다음 접근에서 연결을 다시 잡음.
    """
    if not session.in_transaction():
        return
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("end_read expects a read-only transaction (new/dirty/deleted is not empty)")
    session.commit()
