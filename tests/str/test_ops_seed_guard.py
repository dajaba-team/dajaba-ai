"""ops_seed.sql 자기방어 가드 (SCRUM-158).

적재된 DB(백엔드 Flyway 또는 거래 데이터) 에 사람이 손으로 `psql -f` 하면
49행 `TRUNCATE … CASCADE` 가 돌기 전에 맨 위 `DO $$ ... RAISE EXCEPTION $$` 가
멈춘다. 가드 조건 둘: ① `ops.source_files` 존재(백엔드 Flyway V004_1 표시)
② `ops.transactions` 행 > 3(적재 데이터 있음).

세션 공유 `_ops_seed` 와 안 부딪히게 같은 Testcontainers Postgres 안에 임시 DB 를
만들어 돌린다 — 끝나면 DROP.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS_SEED_SQL = (REPO_ROOT / "tests" / "str" / "fixtures" / "ops_seed.sql").read_text(encoding="utf-8")
GUARD_MESSAGE = "테스트 컨테이너 전용"


@pytest.fixture
def guard_engine(_pg_container) -> Iterator[Engine]:
    """같은 컨테이너에 임시 DB(`ops_seed_guard_<pid>`) 를 만들어 독립 엔진으로 돌린다."""
    admin_url = _pg_container.get_connection_url()
    db_name = f"ops_seed_guard_{os.getpid()}"
    admin = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin.dispose()

    tmp_url = admin_url.rsplit("/", 1)[0] + f"/{db_name}"
    engine = create_engine(tmp_url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()
        admin = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
        try:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        finally:
            admin.dispose()


def _ops_transactions_count(engine: Engine) -> int:
    with engine.begin() as conn:
        return int(conn.execute(text("SELECT count(*) FROM ops.transactions")).scalar_one())


def _source_files_count(engine: Engine) -> int:
    with engine.begin() as conn:
        return int(conn.execute(text("SELECT count(*) FROM ops.source_files")).scalar_one())


def test_guard_blocks_when_source_files_exists(guard_engine: Engine) -> None:
    """백엔드 Flyway 표시(`ops.source_files`) 가 있는 DB 면 `TRUNCATE` 전에 멈춘다."""
    # 빈 DB 라 1차는 가드 통과 → 시드 3행 들어감
    with guard_engine.begin() as conn:
        conn.execute(text(OPS_SEED_SQL))
    assert _ops_transactions_count(guard_engine) == 3

    # 백엔드 Flyway V004_1 표시를 심어 놓고 2차 시도
    with guard_engine.begin() as conn:
        conn.execute(text("CREATE TABLE ops.source_files (id bigint PRIMARY KEY)"))
        conn.execute(text("INSERT INTO ops.source_files (id) VALUES (1)"))

    # 실행 전
    before_sf = _source_files_count(guard_engine)
    before_tx = _ops_transactions_count(guard_engine)
    assert (before_sf, before_tx) == (1, 3)

    with pytest.raises(DBAPIError) as exc_info, guard_engine.begin() as conn:
        conn.execute(text(OPS_SEED_SQL))
    assert GUARD_MESSAGE in str(exc_info.value)

    # 실행 전 == 실행 후 — 심어 둔 행과 시드 3행 전부 그대로(TRUNCATE 안 돈 것)
    after_sf = _source_files_count(guard_engine)
    after_tx = _ops_transactions_count(guard_engine)
    assert (before_sf, before_tx) == (after_sf, after_tx)


def test_guard_blocks_when_transactions_row_count_over_three(guard_engine: Engine) -> None:
    """백엔드 표시가 없어도 `ops.transactions` 행 > 3 이면 멈춘다 — 적재 데이터 보호."""
    # 1차는 가드 통과 → 시드 3행
    with guard_engine.begin() as conn:
        conn.execute(text(OPS_SEED_SQL))
    assert _ops_transactions_count(guard_engine) == 3

    # 적재 데이터 흉내 — 거래 하나 추가해 4행
    with guard_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO ops.transactions (transaction_id, ts) VALUES (999, '2026-01-01 00:00:00')")
        )

    # 실행 전 — 4행 + 999 존재
    before_tx = _ops_transactions_count(guard_engine)
    with guard_engine.begin() as conn:
        before_has_999 = conn.execute(
            text("SELECT 1 FROM ops.transactions WHERE transaction_id = 999")
        ).scalar()
    assert (before_tx, before_has_999) == (4, 1)

    with pytest.raises(DBAPIError) as exc_info, guard_engine.begin() as conn:
        conn.execute(text(OPS_SEED_SQL))
    assert GUARD_MESSAGE in str(exc_info.value)

    # 실행 전 == 실행 후 — 999 지워지지도, 시드 3행으로 돌아가지도 않음
    after_tx = _ops_transactions_count(guard_engine)
    with guard_engine.begin() as conn:
        after_has_999 = conn.execute(
            text("SELECT 1 FROM ops.transactions WHERE transaction_id = 999")
        ).scalar()
    assert (before_tx, before_has_999) == (after_tx, after_has_999)
