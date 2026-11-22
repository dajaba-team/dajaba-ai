"""승인 STR 청크 — 섹션 안 순번 (SCRUM-361, docs/shared/03 · str/10 "승인 STR 색인").

섹션(≤5000자)을 ≤1200자 청크 여러 개로 나누므로 섹션당 한 행 제약을 (문서번호, 섹션, 순번) 으로 바꾼다.
기존 행은 순번 1 · `chunk_id` 끝에 `:1` (새 키 `{report_no}:{section}:{순번}` 과 같은 모양).
downgrade 는 순번 2 이상 행이 있으면 멈춘다 — 승인 STR 을 지워서 되돌리지 않는다.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_str_reference_chunk_seq"
down_revision = "0008_str_reference_chunks"
branch_labels = None
depends_on = None

_TABLE = "ai.str_reference_chunks"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN chunk_seq INTEGER NOT NULL DEFAULT 1 CHECK (chunk_seq >= 1)")
    op.execute(sa.text(f"UPDATE {_TABLE} SET chunk_id = chunk_id || '\\:1'"))  # `:1` 은 바인드 변수가 아님
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT uq_str_reference_chunks_report_section")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT uq_str_reference_chunks_report_section_seq "
        "UNIQUE (report_no, section, chunk_seq)"
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM {_TABLE} WHERE chunk_seq > 1) THEN
                RAISE EXCEPTION '0009 downgrade: chunk_seq > 1 rows exist — split STR chunks would be lost';
            END IF;
        END $$
        """
    )
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT uq_str_reference_chunks_report_section_seq")
    op.execute(
        sa.text(
            f"UPDATE {_TABLE} SET chunk_id = left(chunk_id, length(chunk_id) - 2) WHERE chunk_id LIKE '%\\:1'"
        )
    )
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT uq_str_reference_chunks_report_section UNIQUE (report_no, section)"
    )
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN chunk_seq")
