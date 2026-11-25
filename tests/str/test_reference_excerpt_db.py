"""SCRUM-425 참고 사례 검색 — 실제 PG(-m db): 저장소가 청크 본문을 읽어 `excerpt` 를 채움 · 응답에 원문 `text` 없음."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.str import ReferenceSearchRequest
from aml_ai.str.application.reference_search_service import EmbeddingCache, ReferenceSearchService
from aml_ai.str.infrastructure.reference_search_repository import ReferenceSearchRepository
from aml_ai.str.infrastructure.reference_snippet import reference_excerpt
from tests.str.retriever_search_support import FakeEmbedder, insert_chunk, vec

pytestmark = pytest.mark.db

BODY = "General supervision notes. Many senders deposit cash into one account at once. Closing remarks."


@pytest.fixture
def session(_db_engine: Engine) -> Iterator[Session]:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
        insert_chunk(
            conn, doc_id="a", doc_title="A", page=1, typologies=["FAN_IN"], text_body=BODY, v=vec(1.0)
        )
    with sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)() as s:
        yield s


def test_repository_reads_body_and_service_fills_excerpt(session: Session) -> None:
    s = Settings(_env_file=None, EMBEDDING_MODEL="test-embed")
    v = FakeEmbedder(vec(1.0)).embed(["q"])[0]
    svc = ReferenceSearchService(
        settings=s, repo=ReferenceSearchRepository(session), embed=lambda _t, _d: v,
        retrieval_version="test-embed@00000000", cache=EmbeddingCache(25),
    )  # fmt: skip
    out = svc.search(ReferenceSearchRequest.model_validate({"typologies": ["FAN_IN"]}), None)
    (r,) = out.results
    assert r.excerpt == reference_excerpt(BODY, "FAN_IN") and r.excerpt.startswith("Many senders")
    dumped = json.loads(out.model_dump_json())["results"][0]
    assert "text" not in dumped and BODY not in json.dumps(dumped)
