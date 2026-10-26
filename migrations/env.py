"""Alembic env. URL 은 .env(Settings) 에서. ai 스키마만 다룬다 — ops 는 백엔드 Flyway 의 것."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

import aml_ai.str.infrastructure.orm  # noqa: F401  — 모델 등록
from aml_ai.shared.config import get_settings
from aml_ai.shared.db import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    return getattr(obj, "schema", "ai") == "ai"


def run_migrations_online() -> None:
    engine = create_engine(get_settings().sqlalchemy_url)
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            include_schemas=True,
            include_object=include_object,
            version_table_schema="ai",
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
