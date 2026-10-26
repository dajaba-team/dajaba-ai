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
