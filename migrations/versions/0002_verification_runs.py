"""0002 — verification_runs (docs/shared/03, SCRUM-57).

검증 결과 저장 + 백엔드 ApprovalGate 가 비교하는 narrative_sha256.
번호 재배정: 준영 점수 쪽 3테이블은 0003, reference_chunks(pgvector)는 0004.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SCHEMA = "ai"


def upgrade() -> None:
    op.create_table(
        "verification_runs",
        sa.Column("verification_id", sa.String(32), primary_key=True),
        sa.Column("generation_id", sa.String(32), nullable=False),
        sa.Column("draft_id", sa.String(64), nullable=False),
        sa.Column("revision_no", sa.Integer, nullable=False),
        sa.Column("code_checks", postgresql.JSONB, nullable=False),
        sa.Column("llm_checks", postgresql.JSONB),
        sa.Column("passed", sa.Boolean, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("verifier_version", sa.String(64), nullable=False),
        sa.Column("narrative_sha256", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_verification_runs_draft_id",
        "verification_runs",
        ["draft_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_verification_runs_generation_id",
        "verification_runs",
        ["generation_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_verification_runs_generation_id",
        table_name="verification_runs",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_verification_runs_draft_id",
        table_name="verification_runs",
        schema=SCHEMA,
    )
    op.drop_table("verification_runs", schema=SCHEMA)
