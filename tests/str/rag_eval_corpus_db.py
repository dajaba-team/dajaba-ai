"""SCRUM-305 실행 도구의 DB 읽기 (docs/str/10 "305 실행 기록" 검색 시작 문 3 — 추가 검토 4). 읽기 전용.

`snapshot_session` = `REPEATABLE READ` 읽기 전용 트랜잭션 하나 — `run` 은 태그 집계와 전체 검색을 이 세션 하나에서 해서,
그 사이 다른 세션이 복원·적재를 커밋해도 집계 당시 코퍼스를 본다. 검색은 PG 만(ES 안 씀).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.db import get_engine
from tests.str.rag_eval_corpus_guard import TAGGED_KEYS
from tests.str.rag_eval_corpus_preflight import NEW_DOC_IDS

FAN_TAG_KEYS = ("FAN_IN", "FAN_OUT")


@contextmanager
def snapshot_session() -> Iterator[Session]:
    with Session(get_engine()) as session, session.begin():
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        yield session


@contextmanager
def _session(given: Session | None) -> Iterator[Session]:
    if given is not None:
        yield given
        return
    with Session(get_engine()) as session, session.begin():
        session.execute(text("SET TRANSACTION READ ONLY"))
        yield session


def read_tags(session: Session | None = None) -> tuple[dict[str, list[str]], int, int]:
    """({유형: 태그된 chunk_id}, 새 3문서 FAN 태그 청크 수, 전체 청크 수). 세션을 주면 그 스냅샷에서."""
    with _session(session) as s:
        rows = s.execute(text("SELECT chunk_id, doc_id, typologies FROM ai.reference_chunks")).all()
    ids = {t: sorted(r.chunk_id for r in rows if t in (r.typologies or [])) for t in TAGGED_KEYS}
    fan = sum(1 for r in rows if r.doc_id in NEW_DOC_IDS and set(FAN_TAG_KEYS) & set(r.typologies or []))
    return ids, fan, len(rows)


def fan_counts() -> dict[str, int]:
    with _session(None) as s:
        rows = s.execute(text("SELECT typologies FROM ai.reference_chunks")).all()
    return {t: sum(1 for r in rows if t in (r.typologies or [])) for t in FAN_TAG_KEYS}


def read_corpus(session: Session | None = None) -> dict[str, tuple[str, int, tuple[str, ...]]]:
    """{chunk_id: (문서, 쪽, 태그 정렬 튜플)} — 기대 코퍼스 전체 대조용(같은 스냅샷 세션, 태그 도구 ⑱)."""
    with _session(session) as s:
        rows = s.execute(text("SELECT chunk_id, doc_id, page, typologies FROM ai.reference_chunks")).all()
    return {r.chunk_id: (r.doc_id, r.page, tuple(sorted(r.typologies or []))) for r in rows}
