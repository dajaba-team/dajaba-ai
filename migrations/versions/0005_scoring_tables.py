"""채점 테이블과 공개 v0.1.0rc1 모델 등록."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0005_scoring_tables"
down_revision = "0004_reference_chunks"
branch_labels = None
depends_on = None

# v0.1.0rc1 (73ce24173b4f504aed911df8e641bcbeee96a869)의 고정 서빙 메타데이터.
_RC1 = {
    "model_version": "xgb-medium-c2-31-w1-d4-dev130",
    "feature_version": "medium-evidence31-96h-candidate-dev130",
    "algorithm": "XGBoost",
    "threshold": "0.5",
    "artifact_path": "aml_ml/models/candidate.ubj",
    "is_serving": True,
}


def upgrade() -> None:
    models = op.create_table(
        "model_versions",
        sa.Column("model_version", sa.Text, primary_key=True),
        sa.Column("feature_version", sa.Text, nullable=False),
        sa.Column("algorithm", sa.Text, nullable=False),
        sa.Column("train_period", sa.Text),
        sa.Column("input_hash", sa.Text),
        sa.Column("threshold", sa.Numeric, nullable=False),
        sa.Column("metrics", pg.JSONB),
        sa.Column("artifact_path", sa.Text, nullable=False),
        sa.Column("is_serving", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="ai",
    )
    op.create_index(
        "model_versions_single_serving",
        "model_versions",
        ["is_serving"],
        unique=True,
        postgresql_where=sa.text("is_serving"),
        schema="ai",
    )
    op.bulk_insert(models, [_RC1])
    op.create_table(
        "alert_features",
        sa.Column("alert_id", sa.Text, primary_key=True),
        sa.Column("as_of", sa.DateTime, primary_key=True),
        sa.Column("feature_version", sa.Text, primary_key=True),
        sa.Column("features", pg.JSONB, nullable=False),
        sa.Column("data_quality_status", sa.Text, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="ai",
    )
    op.create_table(
        "predictions",
        sa.Column("prediction_id", sa.Text, primary_key=True),
        sa.Column("alert_id", sa.Text, nullable=False),
        sa.Column("batch_run_id", sa.BigInteger, nullable=False),
        sa.Column("model_version", sa.Text, sa.ForeignKey("ai.model_versions.model_version"), nullable=False),
        sa.Column("feature_version", sa.Text, nullable=False),
        sa.Column("score", sa.Numeric),
        sa.Column("threshold", sa.Numeric, nullable=False),
        sa.Column("data_quality_status", sa.Text, nullable=False),
        sa.Column("failure_code", sa.Text),
        sa.Column("reasons", pg.JSONB, nullable=False),
        sa.Column("evidence_transaction_ids", pg.ARRAY(sa.BigInteger), nullable=False),
        sa.Column("context_transaction_ids", pg.ARRAY(sa.BigInteger), nullable=False),
        sa.Column("request_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="ai",
    )
    op.create_index("predictions_batch_run_idx", "predictions", ["batch_run_id"], schema="ai")


def downgrade() -> None:
    op.drop_table("predictions", schema="ai")
    op.drop_table("alert_features", schema="ai")
    op.drop_table("model_versions", schema="ai")
