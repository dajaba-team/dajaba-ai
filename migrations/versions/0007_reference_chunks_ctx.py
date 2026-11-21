"""청크 맥락 새 표 — reference_chunks 와 같은 칸·인덱스, 임베딩만 머리말 붙인 문장 (SCRUM-308-3, str/10 "청크 맥락")."""

from alembic import op

revision = "0007_reference_chunks_ctx"
down_revision = "0006_serving_package_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ai.reference_chunks_ctx (
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
    op.execute(
        "CREATE INDEX ix_reference_chunks_ctx_embedding ON ai.reference_chunks_ctx "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_reference_chunks_ctx_typologies ON ai.reference_chunks_ctx USING gin (typologies)"
    )


def downgrade() -> None:
    op.drop_table("reference_chunks_ctx", schema="ai")
