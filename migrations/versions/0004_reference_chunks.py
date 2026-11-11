"""참고 사례 청크와 유형·벡터 검색 인덱스."""

import sqlalchemy as sa
from alembic import op

revision = "0004_reference_chunks"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    installed = op.get_bind().execute(sa.text("SELECT 1 FROM pg_extension WHERE extname='vector'")).scalar()
    if not installed:
        raise RuntimeError("pgvector 확장 없음 — shared/03 절차")
    _create_table()
    op.execute(
        "CREATE INDEX ix_reference_chunks_embedding ON ai.reference_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX ix_reference_chunks_typologies ON ai.reference_chunks USING gin (typologies)")


def _create_table() -> None:
    op.execute(
        """
        CREATE TABLE ai.reference_chunks (
            chunk_id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            doc_title TEXT NOT NULL,
            publisher TEXT,
            year INTEGER,
            page INTEGER NOT NULL,
            section TEXT,
            lang TEXT,
            typologies TEXT[] NOT NULL DEFAULT '{}',
            text TEXT NOT NULL,
            embedding vector(1536) NOT NULL,
            embedding_model TEXT NOT NULL,
            content_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.drop_table("reference_chunks", schema="ai")
