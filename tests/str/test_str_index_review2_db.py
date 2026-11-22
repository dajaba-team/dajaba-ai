"""SCRUM-310 추가 검토 1·2 DB 회귀(-m db) — 같은 번호 다른 본문 동시 · 모델 바꾼 뒤 저장된 버전 · REPEATABLE READ 에서 부모 한 벌 ·
원천 표의 실제 계좌(케이스 조각·정확 일치) · 초안 facts 없음."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import InvalidRequest
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import StrIndexStatus
from aml_ai.str.application.str_index_service import StrIndexService
from aml_ai.str.infrastructure.str_index_repository import StrIndexRepository
from tests.str.str_index_db_support import VecEmbed as _Vec
from tests.str.str_index_db_support import count_chunks as _count
from tests.str.str_index_db_support import factory  # noqa: F401 — 픽스처
from tests.str.str_index_db_support import make_svc as _svc
from tests.str.str_index_support import ON, req, with_text

pytestmark = pytest.mark.db


def test_concurrent_same_number_different_bodies(factory: sessionmaker[Session]) -> None:  # noqa: F811
    """같은 번호 · 다른 본문 동시 두 요청 → 한쪽 INDEXED, 다른 쪽 400 · 행은 한 벌(추가 검토 1)."""
    gate, results = threading.Barrier(2), []

    class Slow(_Vec):
        def embed(self, texts: list[str]) -> list[list[float]]:
            gate.wait(timeout=5)
            return super().embed(texts)

    def run(r) -> None:  # noqa: ANN001
        with factory() as s:
            try:
                results.append(_svc(s, Slow()).index(r).status.value)
            except InvalidRequest:
                results.append("400")

    other = req().model_copy(update={"typologies": [Typology.CYCLE]})
    threads = [threading.Thread(target=run, args=(r,)) for r in (req(), other)]
    [t.start() for t in threads]
    [t.join(timeout=10) for t in threads]
    with factory() as s:
        assert sorted(results) == ["400", "INDEXED"] and _count(s) == 4


def test_reindex_after_model_change_keeps_stored_version(factory: sessionmaker[Session]) -> None:  # noqa: F811
    with factory() as s:
        first = _svc(s).index(req())
    changed = Settings(_env_file=None, **{**ON, "EMBEDDING_MODEL": "other-embed"})
    with factory() as s:
        e = _Vec()
        second = StrIndexService(settings=changed, repo=StrIndexRepository(s), embedder=e,
                                 retrieval_version="other-embed@99999999").index(req())  # fmt: skip
        stored = s.execute(text("SELECT retrieval_version FROM ai.str_reference_docs")).scalars().all()
    assert second.retrieval_version == first.retrieval_version == stored[0] and e.calls == []


def test_repeatable_read_two_bodies_one_parent(_db_engine: Engine, factory: sessionmaker[Session]) -> None:  # noqa: F811
    """DB 기본이 REPEATABLE READ 여도 같은 번호 · 섹션이 안 겹치는 두 본문 → 부모 한 벌(INDEXED 1 · 400 1, 추가 검토 2)."""
    rr = sessionmaker(
        bind=_db_engine.execution_options(isolation_level="REPEATABLE READ"), expire_on_commit=False
    )
    gate, results = threading.Barrier(2), []

    class Slow(_Vec):
        def embed(self, texts: list[str]) -> list[list[float]]:
            gate.wait(timeout=5)
            return super().embed(texts)

    a = req()
    b = req(sections=[{"section": "OPINION", "text": "다른 본문의 종합의견 섹션입니다. " * 12}])

    def run(r) -> None:  # noqa: ANN001
        with rr() as s:
            try:
                results.append(_svc(s, Slow()).index(r).status.value)
            except InvalidRequest:
                results.append("400")

    threads = [threading.Thread(target=run, args=(r,)) for r in (a, b)]
    [t.start() for t in threads]
    [t.join(timeout=10) for t in threads]
    with factory() as s:
        docs = s.execute(text("SELECT count(*) FROM ai.str_reference_docs")).scalar_one()
        hashes = s.execute(text("SELECT count(DISTINCT report_no) FROM ai.str_reference_chunks")).scalar_one()
    assert sorted(results) == ["400", "INDEXED"] and docs == 1 and hashes == 1


@pytest.mark.parametrize(
    "raw",
    [
        "상대 계좌 C00000 로",
        "상대 계좌 020-C000-0002 로",
        "상대 계좌 777_ABCDEF123 로",
        "상대 계좌 ABCDEF123 로",
    ],
)
def test_real_accounts_from_source_tables(factory: sessionmaker[Session], raw: str) -> None:  # noqa: F811
    """케이스 계좌(거래 ID 로 읽은 상대 계좌) 조각 · 원천 계좌 표 정확 일치 → RAW_ACCOUNT · 임베딩 0 · 행 0."""
    with factory() as s:
        s.execute(text("INSERT INTO ops.accounts (account_key, bank_name, entity_id) VALUES ('777_ABCDEF123', 'B', '80062E240') "
                       "ON CONFLICT DO NOTHING"))  # fmt: skip
        s.commit()
        e = _Vec()
        out = _svc(s, e).index(with_text(raw))
        assert (
            out.status is StrIndexStatus.SKIPPED and out.skip_reason.value == "RAW_ACCOUNT" and e.calls == []
        )
        assert _count(s) == 0


def test_no_facts_for_draft(factory: sessionmaker[Session]) -> None:  # noqa: F811
    with factory() as s:
        out = _svc(s).index(req(draft_id="DRF-NOT-THERE"))
        assert out.skip_reason.value == "NO_FACTS" and _count(s) == 0
