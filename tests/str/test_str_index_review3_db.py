"""SCRUM-310 추가 검토 3 DB 회귀(-m db) — facts 거래 일부 누락 503·행 0 · 색인 뒤 facts 유실 재요청(같으면 INDEXED, 다르면 400) ·
과다 노출 마스킹 RAW·부모·청크 0행."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.errors import DbUnavailable, InvalidRequest
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import StrIndexStatus
from tests.str.str_index_db_support import (
    FACTS,
    factory,  # noqa: F401 — 픽스처
)
from tests.str.str_index_db_support import VecEmbed as _Vec
from tests.str.str_index_db_support import make_svc as _svc
from tests.str.str_index_support import req, with_text

pytestmark = pytest.mark.db


def _rows(s: Session) -> tuple[int, int]:
    docs = s.execute(text("SELECT count(*) FROM ai.str_reference_docs")).scalar_one()
    return docs, s.execute(text("SELECT count(*) FROM ai.str_reference_chunks")).scalar_one()


def test_partial_source_transactions_503(factory: sessionmaker[Session]) -> None:  # noqa: F811
    """facts 거래 ID 에 원천 표에 없는 999 를 섞음 → 임베딩 전 503 · 행 0."""
    broken = {
        **FACTS,
        "inbound": {**FACTS["inbound"], "transaction_ids": [*FACTS["inbound"]["transaction_ids"], 999]},
    }
    with factory() as s:
        s.execute(text("UPDATE ai.generations SET facts = CAST(:f AS json) WHERE draft_id = 'DRF-000312'"),
                  {"f": json.dumps(broken)})  # fmt: skip
        s.commit()
        e = _Vec()
        with pytest.raises(DbUnavailable):
            _svc(s, e).index(req())
        assert e.calls == [] and _rows(s) == (0, 0)


def test_reindex_after_facts_lost(factory: sessionmaker[Session]) -> None:  # noqa: F811
    with factory() as s:
        assert _svc(s).index(req()).chunk_count == 4
        s.execute(text("DELETE FROM ai.generations WHERE draft_id = 'DRF-000312'"))
        s.commit()
    with factory() as s:
        e = _Vec()
        again = _svc(s, e).index(req())
        assert again.status is StrIndexStatus.INDEXED and again.chunk_count == 4 and e.calls == []
        with pytest.raises(InvalidRequest):
            _svc(s, e).index(req().model_copy(update={"typologies": [Typology.CYCLE]}))
        assert _rows(s) == (1, 4)


def test_masked_then_full_account_raw_no_rows(factory: sessionmaker[Session]) -> None:  # noqa: F811
    with factory() as s:
        e = _Vec()
        out = _svc(s, e).index(with_text("상대 계좌 020_****C0000001 로 보냄."))
        assert out.skip_reason.value == "RAW_ACCOUNT" and e.calls == [] and _rows(s) == (0, 0)
