"""SCRUM-310 승인 STR 색인 DB 테스트 공용(-m db) — 공개 자료·원천 표·초안 facts 시드 · 가짜 임베딩 · 서비스 조립."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.str.application.str_index_service import StrIndexService
from aml_ai.str.infrastructure.str_index_repository import StrIndexRepository
from tests.str.retriever_search_support import FAN_IN_FAN_OUT_SEED, insert_chunk, vec
from tests.str.str_index_support import ON, VERSION, Embed


class VecEmbed(Embed):
    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        if self.fail:
            raise RetrievalUnavailable("down")
        return [vec(1.0) for _ in texts]  # 공개 자료 FAN_IN 질의와 같은 벡터 — 새 표를 읽으면 위로 올라옴


FACTS = json.loads((Path(__file__).parent / "fixtures" / "facts_fan_in.json").read_text(encoding="utf-8"))


@pytest.fixture
def factory(_db_engine: Engine, _ops_seed: None) -> Iterator[sessionmaker[Session]]:
    """공개 자료 시드 + 원천 표(ops_seed — 대상 10_8000EBD30·상대 020_C000000x·거래 1~3) + 예시 draft_id 의 초안 facts 행."""
    with _db_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE ai.reference_chunks, ai.str_reference_chunks, ai.str_reference_docs, ai.generations"
            )
        )
        for row in FAN_IN_FAN_OUT_SEED:
            insert_chunk(conn, **row)
        conn.execute(text("INSERT INTO ai.generations (generation_id, kind, draft_id, facts, request, request_hash, status) "
                          "VALUES ('g-310', 'DRAFT', 'DRF-000312', CAST(:f AS json), '{}', 'h', 'SUCCEEDED')"),
                     {"f": json.dumps(FACTS)})  # fmt: skip
    yield sessionmaker(bind=_db_engine, expire_on_commit=False, future=True)
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.str_reference_chunks, ai.str_reference_docs, ai.generations"))


def make_svc(s: Session, embed: Embed | None = None) -> StrIndexService:
    return StrIndexService(settings=Settings(_env_file=None, **ON), repo=StrIndexRepository(s),
                           embedder=embed or VecEmbed(), retrieval_version=VERSION)  # fmt: skip


def count_chunks(s: Session) -> int:
    return s.execute(text("SELECT count(*) FROM ai.str_reference_chunks")).scalar_one()
