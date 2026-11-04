"""평가자 모델·토큰·지연·시도 수 기록 (SCRUM-92)."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "verification_runs", sa.Column("judge_llm_model", sa.String(128), nullable=True), schema="ai"
    )
    op.add_column("verification_runs", sa.Column("judge_tokens_in", sa.Integer(), nullable=True), schema="ai")
    op.add_column(
        "verification_runs", sa.Column("judge_tokens_out", sa.Integer(), nullable=True), schema="ai"
    )
    op.add_column(
        "verification_runs", sa.Column("judge_latency_ms", sa.Integer(), nullable=True), schema="ai"
    )
    op.add_column(
        "verification_runs", sa.Column("judge_attempts", sa.SmallInteger(), nullable=True), schema="ai"
    )


def downgrade() -> None:
    op.drop_column("verification_runs", "judge_attempts", schema="ai")
    op.drop_column("verification_runs", "judge_latency_ms", schema="ai")
    op.drop_column("verification_runs", "judge_tokens_out", schema="ai")
    op.drop_column("verification_runs", "judge_tokens_in", schema="ai")
    op.drop_column("verification_runs", "judge_llm_model", schema="ai")
