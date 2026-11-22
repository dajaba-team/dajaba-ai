"""승인 STR 색인 표 — 문서(부모) + 섹션 청크, 공개 자료 표와 따로 (SCRUM-310, docs/shared/03 · str/10 "승인 STR 색인").

부모 `str_reference_docs`: 문서번호 PK — 같은 번호에 본문 한 벌만(동시 요청·격리 수준과 상관없이 PK 가 막음, 추가 검토 2).
청크 `str_reference_chunks`: 부모 FK · 섹션마다 한 행. 벡터·유형 칸은 `reference_chunks` 와 같은 모양(`vector(1536)` 고정).
지금은 쓰기만(읽는 검색 없음).
"""

from alembic import op

revision = "0008_str_reference_chunks"
down_revision = "0007_reference_chunks_ctx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ai.str_reference_docs (
            report_no TEXT PRIMARY KEY,
            draft_id TEXT NOT NULL,
            section_set TEXT NOT NULL CHECK (section_set IN ('V1', 'V2')),
            typologies TEXT[] NOT NULL DEFAULT '{}',
            request_hash TEXT NOT NULL,
            retrieval_version TEXT NOT NULL,
            chunk_count INTEGER NOT NULL CHECK (chunk_count >= 1),
            approved_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ai.str_reference_chunks (
            chunk_id TEXT PRIMARY KEY,
            report_no TEXT NOT NULL REFERENCES ai.str_reference_docs (report_no),
            section TEXT NOT NULL,
            typologies TEXT[] NOT NULL DEFAULT '{}',
            text TEXT NOT NULL,
            embedding vector(1536) NOT NULL,
            embedding_model TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_str_reference_chunks_report_section UNIQUE (report_no, section)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_str_reference_chunks_embedding ON ai.str_reference_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_str_reference_chunks_typologies ON ai.str_reference_chunks USING gin (typologies)"
    )


def downgrade() -> None:
    op.drop_table("str_reference_chunks", schema="ai")
    op.drop_table("str_reference_docs", schema="ai")
