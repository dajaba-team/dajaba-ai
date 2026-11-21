"""SCRUM-308-2 추가 검토 5 — 운영 검색·빈칸 채우기 cosine 은 질의 모델과 같은 `embedding_model` 행만(-m db).

리랭커를 끈 기본 경로: 질의 모델 B + 차원이 같은 모델 A 저장 행 → A 행 0. 같은 모델이면 기존 결과 그대로.
"""

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


class _ModelEmbedder(FakeEmbedder):
    def __init__(self, v: list[float], model: str) -> None:
        super().__init__(v)
        self.model = model  # type: ignore[misc]


@pytest.fixture
def session(_db_engine: Engine) -> Iterator[Session]:
    """FAN_IN 3 + FAN_OUT 1 을 모두 모델 "test-embed"(= A) 로 넣음."""
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
        ids = [insert_chunk(conn, **row) for row in FAN_IN_FAN_OUT_SEED]
    with sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)() as s:
        s.info["ids"] = ids
        yield s


def test_same_model_keeps_existing_results(mixed: Facts, session: Session) -> None:
    out = Retriever(session=session, embedder=FakeEmbedder(vec(1.0)), enabled=True).retrieve(
        facts_typology(mixed, Typology.FAN_IN)
    )
    assert len(out) == 3


@pytest.mark.parametrize("typology_filter", [True, False])
def test_other_model_query_sees_no_rows(mixed: Facts, session: Session, typology_filter: bool) -> None:
    retriever = Retriever(
        session=session,
        embedder=_ModelEmbedder(vec(1.0), "model-B"),
        enabled=True,
        typology_filter=typology_filter,
    )
    assert retriever.retrieve(facts_typology(mixed, Typology.FAN_IN)) == []  # 리랭커 꺼짐 — A 행 0


def test_cosines_skip_other_model_rows(session: Session) -> None:
    ids = session.info["ids"]
    session.execute(
        text("UPDATE ai.reference_chunks SET embedding_model = 'model-B' WHERE chunk_id = :c"), {"c": ids[0]}
    )
    retriever = Retriever(session=session, embedder=FakeEmbedder(vec(1.0)), enabled=True)
    got = {r.chunk_id for r in retriever._cosines(vec(1.0), ids)}  # noqa: SLF001 — 빈칸 채우기 cosine 조회
    assert ids[0] not in got and got == set(ids[1:])
    session.rollback()
