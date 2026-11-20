"""기존 모델 행에 서빙 패키지 버전을 별도로 기록한다."""

import sqlalchemy as sa
from alembic import op

revision = "0006_serving_package_version"
down_revision = "0005_scoring_tables"
branch_labels = None
depends_on = None

_MODEL_VERSION = "xgb-medium-c2-31-w1-d4-dev130"
_PACKAGE_VERSION = "0.1.0rc2"


def upgrade() -> None:
    op.add_column("model_versions", sa.Column("serving_package_version", sa.Text()), schema="ai")
    models = sa.table(
        "model_versions", sa.column("model_version"), sa.column("serving_package_version"), schema="ai"
    )
    op.execute(
        models.update()
        .where(models.c.model_version == _MODEL_VERSION)
        .values(serving_package_version=_PACKAGE_VERSION)
    )


def downgrade() -> None:
    op.drop_column("model_versions", "serving_package_version", schema="ai")
