"""SCRUM-275 — 빈칸 채우기 실제 pgvector (docs/str/10 "빈칸만 채우기", -m db). 임베딩·ES 는 가짜.

CYCLE 태그 2 + 태그 없는 청크 → 앞 2건 = 필터 켬 결과 그대로 + 1칸(필터 밖, (a) cosine) · SG 0건 유지.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.retriever_search_support import FakeEmbedder, chash, facts_typology, insert_chunk, vec

pytestmark = pytest.mark.db

_CYCLE_SEED = [
    {"doc_id": "ffiec-redflags", "page": 6, "typologies": ["CYCLE"], "text_body": "c1", "v": vec(1.0, 0.3)},
    {"doc_id": "fatf-pml-2018", "page": 40, "typologies": ["CYCLE"], "text_body": "c2", "v": vec(1.0, 0.6)},
    {"doc_id": "fatf-tbml-2020", "page": 12, "typologies": [], "text_body": "u-near", "v": vec(1.0, 0.1)},
    {"doc_id": "fatf-tbml-2020", "page": 13, "typologies": [], "text_body": "u-far", "v": vec(0.0, 1.0)},
    {"doc_id": "ffiec-redflags", "page": 3, "typologies": ["FAN_IN"], "text_body": "f1", "v": vec(1.0, 0.2)},
]


class _Keyword:
    def __init__(self, ids: list[str]) -> None:
        self.ids = ids

    def search(self, lang: str, text: str, size: int) -> list[str]:
        return self.ids[:size]


@pytest.fixture
def cycle_session(_db_engine: Engine) -> Iterator[Session]:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
        for row in _CYCLE_SEED:
            insert_chunk(conn, doc_title=row["doc_id"], **row)
    with sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)() as s:
        yield s


def _retriever(session: Session, *, gap_fill: bool, keyword: _Keyword | None = None) -> Retriever:
    return Retriever(session, FakeEmbedder(vec(1.0)), enabled=True, gap_fill=gap_fill, keyword=keyword,
                     release=session.commit)  # fmt: skip


def test_cycle_keeps_first_two_and_fills_one(mixed: Facts, cycle_session: Session) -> None:
    facts = facts_typology(mixed, Typology.CYCLE)
    before = _retriever(cycle_session, gap_fill=False).retrieve(facts)
    after = _retriever(cycle_session, gap_fill=True).retrieve(facts)
    assert len(before) == 2 and after[:2] == before
    assert len(after) == 3 and after[2].doc_id == "fatf-tbml-2020" and after[2].page == 12
    assert after[2].score == pytest.approx(1.0 / (1.0 + 0.01) ** 0.5, abs=1e-4)  # (a) 기준 cosine


def test_keyword_hit_gets_a_cosine_from_db(mixed: Facts, cycle_session: Session) -> None:
    far = chash("fatf-tbml-2020", 13, "u-far")
    keyword = _Keyword([far, far])
    after = _retriever(cycle_session, gap_fill=True, keyword=keyword).retrieve(
        facts_typology(mixed, Typology.CYCLE)
    )
    filled = after[2]
    assert filled.chunk_id in {far, chash("fatf-tbml-2020", 12, "u-near"), chash("ffiec-redflags", 3, "f1")}
    if filled.chunk_id == far:
        assert filled.score == pytest.approx(0.0, abs=1e-4)


def test_untagged_typology_stays_empty(mixed: Facts, cycle_session: Session) -> None:
    facts = facts_typology(mixed, Typology.SCATTER_GATHER)
    assert _retriever(cycle_session, gap_fill=True, keyword=_Keyword(["x"])).retrieve(facts) == []


def test_unknown_keyword_ids_are_ignored(mixed: Facts, cycle_session: Session) -> None:
    keyword = _Keyword(["0" * 64])
    after = _retriever(cycle_session, gap_fill=True, keyword=keyword).retrieve(
        facts_typology(mixed, Typology.CYCLE)
    )
    assert len(after) == 3 and "0" * 64 not in {r.chunk_id for r in after}


def test_cosine_failure_keeps_session_usable(
    mixed: Facts, cycle_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """채우기 중 PG 2차가 실패해도 1차 결과 반환 + 세션은 다음 쿼리를 받음(savepoint)."""
    facts = facts_typology(mixed, Typology.CYCLE)
    before = _retriever(cycle_session, gap_fill=False).retrieve(facts)
    monkeypatch.setattr(
        "aml_ai.str.infrastructure.retriever.text", lambda sql: text(sql.replace("ANY(:ids)", "ANY(:nope)"))
    )
    assert _retriever(cycle_session, gap_fill=True).retrieve(facts) == before
    assert cycle_session.execute(text("SELECT 1")).scalar() == 1
