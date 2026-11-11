"""SCRUM-125 — Retriever._search 결정적 판 (docs/str/10 "검색", INTENT 테스트 목록, -m db).

유틸·시드 레시피는 `retriever_search_support.py`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.shared.schemas.str.draft import Reference
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
def _retriever_session_factory(_db_engine: Engine) -> sessionmaker[Session]:
    """reference_chunks 를 비우고 세션 팩토리 돌려줌 — 매 테스트가 독립."""
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
    return sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)


@pytest.fixture
def seeded_session(
    _db_engine: Engine, _retriever_session_factory: sessionmaker[Session]
) -> Iterator[Session]:
    """FAN_IN 3청크 + FAN_OUT 1청크 삽입 — 쿼리 [1,0,0] 기준 FAN_IN 순서로 가까움."""
    with _db_engine.begin() as conn:
        for row in FAN_IN_FAN_OUT_SEED:
            insert_chunk(conn, **row)
    with _retriever_session_factory() as s:
        yield s


def test_typology_filter_excludes_other_types(mixed: Facts, seeded_session: Session) -> None:
    """FAN_IN 질의 → FAN_IN 태그 청크 3개만, FAN_OUT 전용 청크는 안 나옴 (오류 주입 14 뼈대)."""
    retriever = Retriever(session=seeded_session, embedder=FakeEmbedder(vec(1.0)), enabled=True)
    result = retriever.retrieve(facts_typology(mixed, Typology.FAN_IN))
    assert len(result) == 3
    p5_ffiec = [r for r in result if r.doc_id == "ffiec-redflags" and r.page == 5]
    assert p5_ffiec == [], "FAN_OUT 전용 청크가 FAN_IN 질의에 나옴"


def test_results_ordered_by_distance(mixed: Facts, seeded_session: Session) -> None:
    """relaxed_order + 바깥 재정렬 — score 내림차순(거리 오름차순) 보장."""
    retriever = Retriever(session=seeded_session, embedder=FakeEmbedder(vec(1.0)), enabled=True)
    result = retriever.retrieve(facts_typology(mixed, Typology.FAN_IN))
    scores = [r.score for r in result]
    assert scores == sorted(scores, reverse=True), f"거리 순서 어긋남: {scores}"
    assert result[0].doc_id == "fincen-funnel-2014"
    assert result[0].page == 1


def test_max_three_results(
    _db_engine: Engine, mixed: Facts, _retriever_session_factory: sessionmaker[Session]
) -> None:
    """RAG_TOP_K=3 — FAN_IN 태그 4개 넣어도 3건."""
    with _db_engine.begin() as conn:
        for i in range(4):
            insert_chunk(
                conn,
                doc_id=f"doc-{i}",
                doc_title=f"Doc {i}",
                page=1,
                typologies=["FAN_IN"],
                text_body=f"text {i}",
                v=vec(0.9 - i * 0.1, 0.05),
            )
    with _retriever_session_factory() as s:
        retriever = Retriever(session=s, embedder=FakeEmbedder(vec(1.0)), enabled=True)
        result = retriever.retrieve(facts_typology(mixed, Typology.FAN_IN))
    assert len(result) == 3


def test_single_matching_chunk_returns_one(
    _db_engine: Engine, mixed: Facts, _retriever_session_factory: sessionmaker[Session]
) -> None:
    """FAN_OUT 태그 청크 1개만 있으면 1건 — 백필 안 함 (INTENT ★A 4)."""
    with _db_engine.begin() as conn:
        insert_chunk(
            conn,
            doc_id="ffiec-redflags",
            doc_title="BSA/AML Appendix F",
            page=5,
            typologies=["FAN_OUT"],
            text_body="Unusually large number of beneficiaries ...",
            v=vec(0.9, 0.05),
        )
        insert_chunk(
            conn,
            doc_id="fincen-funnel-2014",
            doc_title="Funnel Accounts",
            page=1,
            typologies=["FAN_IN"],
            text_body="Funnel Account receives ...",
            v=vec(0.99, 0.01),
        )
    with _retriever_session_factory() as s:
        retriever = Retriever(session=s, embedder=FakeEmbedder(vec(1.0)), enabled=True)
        result = retriever.retrieve(facts_typology(mixed, Typology.FAN_OUT))
    assert len(result) == 1
    assert result[0].doc_id == "ffiec-redflags"


def test_min_similarity_filters_low_scores(
    monkeypatch: pytest.MonkeyPatch,
    _db_engine: Engine,
    mixed: Facts,
    _retriever_session_factory: sessionmaker[Session],
) -> None:
    """MIN_SIMILARITY 임계값 — 그 미만 score 는 결과에서 빠짐."""
    with _db_engine.begin() as conn:
        insert_chunk(
            conn,
            doc_id="near",
            doc_title="Near",
            page=1,
            typologies=["FAN_IN"],
            text_body="near",
            v=vec(0.99, 0.01),
        )
        insert_chunk(
            conn,
            doc_id="far",
            doc_title="Far",
            page=1,
            typologies=["FAN_IN"],
            text_body="far",
            v=vec(0.0, 0.0, 0.99),
        )
    monkeypatch.setattr("aml_ai.str.infrastructure.retriever.MIN_SIMILARITY", 0.5)
    with _retriever_session_factory() as s:
        retriever = Retriever(session=s, embedder=FakeEmbedder(vec(1.0)), enabled=True)
        result = retriever.retrieve(facts_typology(mixed, Typology.FAN_IN))
    assert len(result) == 1
    assert result[0].doc_id == "near"
    assert result[0].score >= 0.5


def test_none_typology_returns_empty(mixed: Facts, seeded_session: Session) -> None:
    """facts.typology=None → retrieve() 가 [] (INTENT ★A 4)."""
    retriever = Retriever(session=seeded_session, embedder=FakeEmbedder(vec(1.0)), enabled=True)
    assert retriever.retrieve(facts_typology(mixed, None)) == []


def test_reference_has_chunk_id_filled(mixed: Facts, seeded_session: Session) -> None:
    """반환 Reference.chunk_id 는 content_hash 와 같은 값 (INTENT ★A 3)."""
    retriever = Retriever(session=seeded_session, embedder=FakeEmbedder(vec(1.0)), enabled=True)
    result = retriever.retrieve(facts_typology(mixed, Typology.FAN_IN))
    assert result, "결과 비었음 — 유형 필터 또는 삽입 데이터 문제"
    for r in result:
        assert isinstance(r, Reference)
        assert r.chunk_id is not None
        assert len(r.chunk_id) == 64


# test_rare_typology_beyond_default_ef_search_still_returned 는 `test_retriever_search_hnsw.py` 로 분리.
# test_search_failure_preserves_outer_writes 는 `test_retriever_search_savepoint.py` 로 분리.


def test_candidates_resorted_by_distance(
    _db_engine: Engine, mixed: Facts, _retriever_session_factory: sessionmaker[Session]
) -> None:
    """후보 안에서 거리순 재정렬 — cosine 은 방향만 보니 축 다른 벡터로 거리 벌림(스칼라 배수는 거리 0)."""
    rows = [("far", vec(0.7, 0.3)), ("mid", vec(0.9, 0.1)), ("near", vec(0.99, 0.01))]
    with _db_engine.begin() as conn:
        for name, v in rows:  # 삽입 순서 (far → near), 거리순 (near → far)
            insert_chunk(
                conn, doc_id=name, doc_title=name, page=1, typologies=["FAN_IN"], text_body=name, v=v
            )
    with _retriever_session_factory() as s:
        retriever = Retriever(session=s, embedder=FakeEmbedder(vec(1.0)), enabled=True)
        result = retriever.retrieve(facts_typology(mixed, Typology.FAN_IN))
    assert [r.doc_id for r in result] == ["near", "mid", "far"], f"재정렬 실패: {result}"
    assert all(result[i].score >= result[i + 1].score for i in range(len(result) - 1))
