"""0001 — str 쪽 테이블: generations, prompt_versions, fewshot_examples (docs/shared/03).

번호 예약: 0002 점수 쪽 3테이블(준영, W3) · 0003 verification_runs(진희, W3) · 0004 reference_chunks(진희, W4, pgvector 뒤).
ai 스키마·app_ai 계정은 백엔드 db/init/01_roles.sh 가 만든다 — 여기서 CREATE SCHEMA 하지 않는다.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "ai"


def upgrade() -> None:
    _create_generations()
    _create_support_tables()


def _create_generations() -> None:
    op.create_table(
        "generations",
        sa.Column("generation_id", sa.String(32), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("draft_id", sa.String(64)),
        sa.Column("case_no", sa.String(64)),
        sa.Column("facts", postgresql.JSONB),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("request", postgresql.JSONB, nullable=False),
        sa.Column("response", postgresql.JSONB),
        sa.Column("llm_model", sa.String(128)),
        sa.Column("prompt_version", sa.String(64)),
        sa.Column("few_shot_ids", postgresql.ARRAY(sa.Integer)),
        sa.Column("references", postgresql.JSONB),
        sa.Column("retrieval_version", sa.String(128)),
        sa.Column("tokens_in", sa.Integer),
        sa.Column("tokens_out", sa.Integer),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("status", sa.String(16), server_default="PROCESSING", nullable=False),
        sa.Column("finished_at", sa.DateTime),
        sa.Column("error", sa.Text),
        sa.Column("request_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_generations_draft", "generations", ["draft_id", "kind", "created_at"], schema=SCHEMA)

    op.create_index(
        "uq_generations_active_draft",
        "generations",
        ["draft_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("kind='DRAFT' AND status <> 'FAILED'"),
    )


def _create_support_tables() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("prompt_name", sa.String(64), primary_key=True),
        sa.Column("version", sa.String(16), primary_key=True),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )

    op.create_table(
        "fewshot_examples",
        sa.Column("example_id", sa.Integer, primary_key=True),
        sa.Column("typology", sa.String(32), nullable=False),
        sa.Column("facts", postgresql.JSONB, nullable=False),
        sa.Column("narrative", postgresql.JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_fewshot_typology", "fewshot_examples", ["typology"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("fewshot_examples", schema=SCHEMA)
    op.drop_table("prompt_versions", schema=SCHEMA)
    op.drop_table("generations", schema=SCHEMA)
