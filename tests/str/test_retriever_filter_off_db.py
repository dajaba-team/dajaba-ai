"""SCRUM-146 — 평가용 `typology_filter=False` 실제 SQL (docs/str/10, -m db). 켬은 기존 테스트 그대로."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.retriever_search_support import (
    FAN_IN_FAN_OUT_SEED,
    FakeEmbedder,
    facts_typology,
    insert_chunk,
    vec,
)

pytestmark = pytest.mark.db


@pytest.fixture
def seeded(_db_engine: Engine) -> Iterator[Session]:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
        for row in FAN_IN_FAN_OUT_SEED:
            insert_chunk(conn, **row)
    with sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)() as s:
        yield s


@pytest.mark.parametrize("multi", [False, True])
def test_filter_off_returns_other_typology_chunk(mixed: Facts, seeded: Session, multi: bool) -> None:
    """FAN_IN 질의 — 필터 끄면 FAN_OUT 전용 ffiec p.5(가장 가까움)가 나옴, 켜면 안 나옴."""
    facts = facts_typology(mixed, Typology.FAN_IN)
    on = Retriever(seeded, FakeEmbedder(vec(1.0)), enabled=True, multi_query=multi).retrieve(facts)
    off = Retriever(seeded, FakeEmbedder(vec(1.0)), enabled=True, multi_query=multi,
                    typology_filter=False).retrieve(facts)  # fmt: skip
    assert not any(r.doc_id == "ffiec-redflags" and r.page == 5 for r in on)
    assert any(r.doc_id == "ffiec-redflags" and r.page == 5 for r in off)
