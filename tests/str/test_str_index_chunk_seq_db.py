"""0009 승인 STR 청크 순번 — 실제 PG(-m db) (SCRUM-361, docs/shared/03 0009 · str/10 "승인 STR 색인").

긴 섹션이 순번 붙은 여러 행으로 들어감 · UNIQUE(문서번호, 섹션, 순번) · downgrade 는 순번 2 이상이 있으면 멈추고
(행 그대로) 없으면 키 `:1` 을 떼고 되돌림. 끝나면 head 로 다시 올림.
"""

from __future__ import annotations

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.schemas.str import StrIndexRequest, StrIndexStatus
from tests.str.conftest import REPO_ROOT
from tests.str.str_index_db_support import factory  # noqa: F401 — 픽스처
from tests.str.str_index_db_support import make_svc as _svc
from tests.str.str_index_support import body

pytestmark = pytest.mark.db
LONG = ("가" * 499 + ". ") * 9 + "나" * 400  # 4909자 → 5청크


def _long_req() -> StrIndexRequest:
    b = body()
    b["sections"] = [{**b["sections"][0], "text": LONG}, *b["sections"][1:]]
    return StrIndexRequest.model_validate(b)


def _cfg(engine: Engine) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    return cfg


def test_long_section_rows_with_seq(factory: sessionmaker[Session]) -> None:  # noqa: F811
    with factory() as s:
        out = _svc(s).index(_long_req())
        rows = s.execute(
            text(
                "SELECT chunk_id, section, chunk_seq, length(text) FROM ai.str_reference_chunks ORDER BY section, chunk_seq"
            )
        ).all()
        n_doc = s.execute(text("SELECT chunk_count FROM ai.str_reference_docs")).scalar_one()
    subject = [r for r in rows if r.section == "SUBJECT"]
    assert out.status is StrIndexStatus.INDEXED and out.chunk_count == len(rows) == n_doc == 5 + 3
    assert [(r.chunk_seq, r.chunk_id.rsplit(":", 1)[-1]) for r in subject] == [
        (i, str(i)) for i in range(1, 6)
    ]
    assert all(r[3] <= 1200 for r in rows)


def test_unique_report_section_seq(factory: sessionmaker[Session]) -> None:  # noqa: F811
    with factory() as s:
        names = (
            s.execute(
                text("SELECT conname FROM pg_constraint WHERE conrelid = 'ai.str_reference_chunks'::regclass")
            )
            .scalars()
            .all()
        )
    assert "uq_str_reference_chunks_report_section_seq" in names
    assert "uq_str_reference_chunks_report_section" not in names


def test_downgrade_refuses_when_split_rows_exist(factory: sessionmaker[Session], _db_engine: Engine) -> None:  # noqa: F811
    with factory() as s:
        _svc(s).index(_long_req())
    try:
        with pytest.raises(Exception, match="chunk_seq > 1"):
            command.downgrade(_cfg(_db_engine), "0008_str_reference_chunks")
        with factory() as s:
            assert (
                s.execute(
                    text("SELECT count(*) FROM ai.str_reference_chunks WHERE chunk_seq > 1")
                ).scalar_one()
                == 4
            )
    finally:
        command.upgrade(_cfg(_db_engine), "head")


def test_downgrade_restores(factory: sessionmaker[Session], _db_engine: Engine) -> None:  # noqa: F811
    """순번 1 만 있으면 downgrade 가 키 `:1` 을 떼고, 다시 upgrade 하면 붙음."""
    with factory() as s:
        _svc(s).index(StrIndexRequest.model_validate(body()))  # 짧은 섹션 — 순번 1 만
    try:
        command.downgrade(_cfg(_db_engine), "0008_str_reference_chunks")
        with _db_engine.connect() as conn:
            ids = (
                conn.execute(text("SELECT chunk_id FROM ai.str_reference_chunks ORDER BY chunk_id"))
                .scalars()
                .all()
            )
        assert ids and all(i.count(":") == 1 for i in ids)  # `{report_no}:{section}` 로 되돌아감
    finally:
        command.upgrade(_cfg(_db_engine), "head")
    with _db_engine.connect() as conn:
        ids = conn.execute(text("SELECT chunk_id FROM ai.str_reference_chunks")).scalars().all()
    assert ids and all(i.endswith(":1") for i in ids)
