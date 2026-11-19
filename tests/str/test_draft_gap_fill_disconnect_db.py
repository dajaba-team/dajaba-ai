"""SCRUM-275 추가 검토 1 high — 채우기 PG 2차 연결이 실제로 끊겨도 초안은 끝까지 (docs/str/10 "실패하면", -m db).

v4 · 빈칸 채우기 켬 · CYCLE 태그 2청크(1칸 채울 자리). 채우기용 별도 세션의 백엔드를 `pg_terminate_backend` 로
죽인 뒤 초안 생성 → SUCCEEDED, 참고 사례 = 1차 2건 그대로. 임베딩·ES 는 가짜, LLM 0(v4 코드 조립).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.db import end_read
from aml_ai.shared.schemas.str import DraftRequest
from aml_ai.str.application.draft_service import DraftService
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.retriever_search_support import FakeEmbedder, insert_chunk, vec

pytestmark = pytest.mark.db

_SEED = [
    {"doc_id": "ffiec-redflags", "page": 6, "typologies": ["CYCLE"], "text_body": "c1", "v": vec(1.0, 0.3)},
    {"doc_id": "fatf-pml-2018", "page": 40, "typologies": ["CYCLE"], "text_body": "c2", "v": vec(1.0, 0.6)},
    {"doc_id": "fatf-tbml-2020", "page": 12, "typologies": [], "text_body": "u-near", "v": vec(1.0, 0.1)},
]


def _cycle_request(sample: dict) -> DraftRequest:
    body = {**sample, "draft_id": "DRF-SCRUM275-DISCONNECT", "investigator_notes": None}
    body["alert"] = {**body["alert"], "account_key": "10_8000EBD30", "entity_id": "80062E240",
                     "transaction_ids": [1, 2, 3], "typology_hint": "CYCLE"}  # fmt: skip
    body["evidence_transaction_ids"] = [1, 2, 3]
    return DraftRequest.model_validate(body)


def _killed_fill_session(engine: Engine, killed: list[int]):
    @contextmanager
    def open_session() -> Iterator[Session]:
        s = Session(bind=engine)
        pid = s.execute(text("SELECT pg_backend_pid()")).scalar_one()
        with engine.connect() as admin:
            admin.execute(text("SELECT pg_terminate_backend(:p)"), {"p": pid})
            admin.commit()
        killed.append(pid)
        try:
            yield s
        finally:
            s.close()

    return open_session


def test_draft_succeeds_when_fill_connection_is_killed(
    _db_engine: Engine, _ops_seed: None, db_session: Session, draft_request_sample: dict
) -> None:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
        for row in _SEED:
            insert_chunk(conn, doc_title=row["doc_id"], **row)
    settings = Settings(_env_file=None, RAG_ENABLED=True, RAG_GAP_FILL_ENABLED=True, AI_LLM_MOCK=True)
    svc = DraftService.build(db_session, settings)
    killed: list[int] = []
    retriever = Retriever(db_session, FakeEmbedder(vec(1.0)), enabled=True, gap_fill=True,
                          release=lambda: end_read(db_session),
                          fill_session=_killed_fill_session(_db_engine, killed))  # fmt: skip
    svc = dataclasses.replace(svc, retriever=retriever)

    out = svc.create(_cycle_request(draft_request_sample))

    assert killed, "채우기 세션 연결을 끊지 못함 — 2차 경로를 안 탐"
    assert out.generation_meta.prompt_version == "narrative_v4"
    assert [r.doc_id for r in out.generation_meta.references] == [
        "ffiec-redflags",
        "fatf-pml-2018",
    ]  # 1차 그대로
    status = db_session.execute(
        text("SELECT status FROM ai.generations WHERE draft_id = 'DRF-SCRUM275-DISCONNECT'")
    ).scalar_one()
    assert status == "SUCCEEDED"
