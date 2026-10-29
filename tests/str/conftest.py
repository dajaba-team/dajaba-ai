"""tests/str 공용 픽스처."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.schemas.str import Facts
from tests.str.facts_support import CASES, build

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def mixed() -> Facts:
    """facts_cases.json "mixed" — inbound 2통화·outbound·internal·indirect·self-transfer 가 다 있는 경보."""
    return build(CASES["mixed"])


# ── -m db 테스트용 (str/08 "DB" 층). testcontainers + alembic upgrade head ──


@pytest.fixture(scope="session")
def _pg_container() -> Iterator[object]:
    """session 내 Postgres 1개를 공유. -m db 테스트에서만 뜬다. Docker 없으면 전체 skip.

    Ryuk(reaper)은 macOS Docker Desktop 에서 소켓 마운트가 안 돼 끈다 — finally 로 수동 정리.
    """
    pytest.importorskip("testcontainers.postgres")
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
    from testcontainers.postgres import PostgresContainer

    try:
        container = PostgresContainer("postgres:16", driver="psycopg")
        container.start()
    except Exception as exc:  # Docker 미기동 등 — 로컬에서는 조용히 넘어간다
        pytest.skip(f"Docker 로 Postgres 를 띄울 수 없음: {exc}", allow_module_level=False)
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def _db_engine(_pg_container) -> Engine:
    """ai 스키마 + alembic upgrade head 를 한 번만."""
    url = _pg_container.get_connection_url()
    os.environ["DATABASE_URL"] = url
    from aml_ai.shared.config import get_settings

    get_settings.cache_clear()
    engine = create_engine(url, future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS ai"))
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return engine


@pytest.fixture
def db_session(_db_engine) -> Iterator[Session]:
    """함수 범위 세션. ai.generations 를 매 테스트 전에 비운다."""
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.generations RESTART IDENTITY"))
    factory = sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)
    with factory() as s:
        yield s


@pytest.fixture
def db_session_factory(_db_engine) -> sessionmaker[Session]:
    """스레드마다 세션 하나 — 동시 요청 테스트용."""
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.generations RESTART IDENTITY"))
    return sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)


@pytest.fixture
def draft_request_sample() -> dict:
    """contracts/examples/draft_request.json — 선점 테스트의 바디 재료."""
    return json.loads((REPO_ROOT / "contracts" / "examples" / "draft_request.json").read_text())


@pytest.fixture
def draft_response_sample() -> dict:
    """contracts/examples/draft_response.json — SUCCEEDED 재사용 테스트에 저장할 유효 응답."""
    return json.loads((REPO_ROOT / "contracts" / "examples" / "draft_response.json").read_text())
