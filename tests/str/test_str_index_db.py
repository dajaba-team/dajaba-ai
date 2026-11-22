"""SCRUM-310 승인 STR 색인 — 실제 PG(-m db): 새 표 · 같은 번호 두 번 · 다른 본문 400 · 동시 두 요청 · 임베딩 실패 행 0 ·
초안 경로·참고 사례 검색이 새 표를 읽지 않음(공개 자료 검색 결과가 색인 전후로 같음)."""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.errors import InvalidRequest, LlmUnavailable
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts, StrIndexStatus
from aml_ai.str.infrastructure.reference_search_repository import ReferenceSearchRepository
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.retriever_search_support import (
    FakeEmbedder,
    facts_typology,
    vec,
)
from tests.str.str_index_db_support import VecEmbed as _Vec
from tests.str.str_index_db_support import count_chunks as _count
from tests.str.str_index_db_support import factory  # noqa: F401 — 픽스처
from tests.str.str_index_db_support import make_svc as _svc
from tests.str.str_index_support import req

pytestmark = pytest.mark.db


def _cols(s: Session, table: str) -> set[str]:
    q = "SELECT column_name FROM information_schema.columns WHERE table_schema='ai' AND table_name=:t"
    return set(s.execute(text(q), {"t": table}).scalars())


def test_table_columns_and_indexes(factory: sessionmaker[Session]) -> None:  # noqa: F811
    with factory() as s:
        docs, chunks = _cols(s, "str_reference_docs"), _cols(s, "str_reference_chunks")
        idx = set(
            s.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename='str_reference_chunks'")
            ).scalars()
        )
    assert {"report_no", "draft_id", "section_set", "typologies", "request_hash", "retrieval_version", "chunk_count",
            "approved_at", "created_at"} <= docs  # fmt: skip
    assert {
        "chunk_id",
        "report_no",
        "section",
        "typologies",
        "text",
        "embedding",
        "embedding_model",
    } <= chunks
    assert {"ix_str_reference_chunks_embedding", "ix_str_reference_chunks_typologies"} <= idx


def test_same_number_twice_keeps_rows(factory: sessionmaker[Session]) -> None:  # noqa: F811
    e = _Vec()
    with factory() as s:
        first = _svc(s, e).index(req())
    with factory() as s:
        second = _svc(s, e).index(req())
        n = _count(s)
    assert (
        first.status is second.status is StrIndexStatus.INDEXED
        and first.chunk_count == second.chunk_count == n == 4
    )
    assert len(e.calls) == 1  # 두 번째는 임베딩 0


def test_different_body_is_400(factory: sessionmaker[Session]) -> None:  # noqa: F811
    with factory() as s:
        _svc(s).index(req())
    b = req().model_copy(update={"typologies": [Typology.CYCLE]})
    with factory() as s, pytest.raises(InvalidRequest):
        _svc(s).index(b)
    with factory() as s:
        assert _count(s) == 4


def test_concurrent_two_requests_one_set(factory: sessionmaker[Session]) -> None:  # noqa: F811
    gate, results = threading.Barrier(2), []

    class Slow(_Vec):
        def embed(self, texts: list[str]) -> list[list[float]]:
            gate.wait(timeout=5)  # 둘 다 "행 없음" 을 본 뒤 넣으러 감
            return super().embed(texts)

    def run() -> None:
        with factory() as s:
            results.append(_svc(s, Slow()).index(req()).chunk_count)

    threads = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in threads]
    [t.join(timeout=10) for t in threads]
    with factory() as s:
        assert results == [4, 4] and _count(s) == 4


def test_embedding_failure_leaves_no_rows(factory: sessionmaker[Session]) -> None:  # noqa: F811
    with factory() as s, pytest.raises(LlmUnavailable):
        _svc(s, _Vec(fail=True)).index(req())
    with factory() as s:
        assert _count(s) == 0


def test_insert_failure_rolls_back_all(factory: sessionmaker[Session]) -> None:  # noqa: F811
    from aml_ai.shared.errors import DbUnavailable

    with factory() as s:
        e = _Vec()
        e.embed = lambda texts: [vec(1.0)] * (len(texts) - 1) + [[1.0] * 3]  # type: ignore[method-assign]  # 마지막만 차원 틀림
        with pytest.raises((DbUnavailable, LlmUnavailable)):
            _svc(s, e).index(req())
    with factory() as s:
        assert _count(s) == 0  # 일부만 남지 않음


def test_public_search_unchanged_after_index(factory: sessionmaker[Session], mixed: Facts) -> None:  # noqa: F811
    """공개 자료 검색(초안 경로 Retriever · 참고 사례 검색 저장소)이 색인 전후로 같은 결과 — 새 표를 안 읽음."""
    f = facts_typology(mixed, Typology.FAN_IN)

    def both() -> tuple[list, list]:
        with factory() as s:
            draft = [
                (r.chunk_id, round(r.score, 6))
                for r in Retriever(s, FakeEmbedder(vec(1.0)), enabled=True).retrieve(f)
            ]
            search = ReferenceSearchRepository(s).search(vec(1.0), ["FAN_IN"], "test-embed",
                                                         deadline=time.monotonic() + 5, clock=time.monotonic)  # fmt: skip
            return draft, [(h.chunk_id, round(h.score, 6)) for h in search]

    before = both()
    with factory() as s:
        assert _svc(s).index(req()).status is StrIndexStatus.INDEXED
    assert both() == before and before[0] and before[1]
