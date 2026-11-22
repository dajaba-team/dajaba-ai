"""SCRUM-309 참고 사례 검색 — 실제 PG(-m db): 유형 OR 필터 · 같은 모델 · 정리 · 상태 · 본문 칸 0 · DB 오류 503."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import DbUnavailable
from aml_ai.shared.schemas.str import ReferenceSearchRequest, ReferenceSearchStatus
from aml_ai.str.application.reference_search_service import EmbeddingCache, ReferenceSearchService
from aml_ai.str.infrastructure.reference_search_repository import ReferenceSearchRepository
from tests.str.retriever_search_support import FAN_IN_FAN_OUT_SEED, FakeEmbedder, insert_chunk, vec

pytestmark = pytest.mark.db


@pytest.fixture
def session(_db_engine: Engine) -> Iterator[Session]:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
        for row in FAN_IN_FAN_OUT_SEED:
            insert_chunk(conn, **row)
        for p in range(1, 6):  # 한 문서에 FAN_IN 5쪽 — 한 문서 3건 제한 확인
            insert_chunk(
                conn,
                doc_id="many",
                doc_title="Many",
                page=p,
                typologies=["FAN_IN"],
                text_body=f"m{p}",
                v=vec(1.0, 0.01 * p),
            )
        insert_chunk(
            conn,
            doc_id="other-model",
            doc_title="O",
            page=1,
            typologies=["FAN_IN"],
            text_body="o",
            v=vec(1.0),
        )
        conn.execute(
            text("UPDATE ai.reference_chunks SET embedding_model = 'other' WHERE doc_id = 'other-model'")
        )
        conn.execute(
            text("UPDATE ai.reference_chunks SET publisher = 'Pub', year = 2020 WHERE doc_id <> 'many'")
        )
    with sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)() as s:
        yield s


def _svc(session: Session) -> ReferenceSearchService:
    s = Settings(_env_file=None, EMBEDDING_MODEL="test-embed")
    v = FakeEmbedder(vec(1.0)).embed(["q"])[0]
    return ReferenceSearchService(settings=s, repo=ReferenceSearchRepository(session), embed=lambda t, total: v, retrieval_version="test-embed@00000000",
                                  cache=EmbeddingCache(25))  # fmt: skip


def _req(**kw) -> ReferenceSearchRequest:  # noqa: ANN003
    return ReferenceSearchRequest.model_validate({"top_k": 10, **kw})


def test_or_filter_overlap_and_order(session: Session) -> None:
    out = _svc(session).search(_req(typologies=["CYCLE", "FAN_OUT"]), None)
    assert out.status is ReferenceSearchStatus.FOUND
    assert all({t.value for t in r.typologies} & {"CYCLE", "FAN_OUT"} for r in out.results)
    scores = [r.score for r in out.results]
    assert scores == sorted(scores, reverse=True)


def test_per_doc_cap_and_other_model_excluded(session: Session) -> None:
    out = _svc(session).search(_req(typologies=["FAN_IN"]), None)
    docs = [r.doc_id for r in out.results]
    assert docs.count("many") == 3 and "other-model" not in docs
    assert len({r.chunk_id for r in out.results}) == len(out.results)
    many = next(r for r in out.results if r.doc_id == "many")
    assert many.publisher is None and many.year is None  # 없으면 null


def test_untagged_typology_is_empty(session: Session) -> None:
    out = _svc(session).search(_req(typologies=["SCATTER_GATHER"]), None)
    assert out.status is ReferenceSearchStatus.EMPTY and out.results == [] and out.search_meta.candidates == 0


def test_top_k_and_no_text_in_json(session: Session) -> None:
    out = _svc(session).search(_req(typologies=["FAN_IN"], top_k=2), None)
    assert len(out.results) == 2 and '"text"' not in out.model_dump_json()


def test_db_failure_is_503(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    real = session.execute

    def broken(stmt, *a, **kw):  # noqa: ANN001, ANN002, ANN003, ANN202
        if "typologies &&" in str(stmt):
            raise OperationalError("x", {}, Exception("down"))
        return real(stmt, *a, **kw)

    monkeypatch.setattr(session, "execute", broken)
    with pytest.raises(DbUnavailable):
        _svc(session).search(_req(typologies=["FAN_IN"]), None)
    assert real(text("SELECT 1")).scalar() == 1  # savepoint — 세션은 그대로
