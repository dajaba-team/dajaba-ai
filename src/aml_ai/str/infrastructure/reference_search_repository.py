"""SCRUM-309 참고 사례 검색 저장소 — `ai.reference_chunks` 읽기만 (docs/str/10 "참고 사례 검색").

초안 경로 `Retriever` 와 따로 — 초안 검색은 안 바뀜. SQL 은 `retriever_sql.reference_search_sql`(같은 모양).
DB 오류는 503 `DB_UNAVAILABLE`(점수 쪽과 같은 코드). savepoint 안에서 돌려 세션은 그대로 쓸 수 있음.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from aml_ai.shared.errors import DbUnavailable, LlmUnavailable
from aml_ai.str.domain.constants_rag_query import REFERENCE_SEARCH_CANDIDATES
from aml_ai.str.domain.reference_search import Hit
from aml_ai.str.infrastructure.retriever_sql import reference_search_sql

_MS = 1000


def _left(deadline: float, clock: Callable[[], float]) -> float:
    remaining = deadline - clock()
    if remaining <= 0:
        raise LlmUnavailable("reference search budget exhausted")
    return remaining


class ReferenceSearchRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def search(
        self,
        vec: list[float],
        typologies: list[str],
        model: str,
        *,
        deadline: float,
        clock: Callable[[], float],
    ) -> list[Hit]:
        """`deadline` = 절대 마감(단조). 연결을 얻은 **뒤** 남은 시간을 셈 — 0 이하면 검색 SQL 없이 502,
        있으면 그만큼 `statement_timeout`(넘으면 503). 풀 대기로 예산이 끝난 요청은 검색을 시작하지 않음(검토 2) · 설정 왕복 뒤 다시 확인(검토 3)."""
        params = {"vec": str(vec), "tys": typologies, "model": model, "cand": REFERENCE_SEARCH_CANDIDATES}
        try:
            with self._s.begin_nested():
                self._s.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))  # 여기서 연결을 얻음
                ms = str(max(1, int(_left(deadline, clock) * _MS)))
                self._s.execute(text("SELECT set_config('statement_timeout', :ms, true)"), {"ms": ms})
                _left(deadline, clock)  # 설정 왕복 뒤 다시 — 지났으면 검색 SQL 없이 502(검토 3)
                rows = self._s.execute(reference_search_sql(), params).all()
        except SQLAlchemyError as exc:
            raise DbUnavailable("reference search failed", error_type=type(exc).__name__) from exc
        return [
            Hit(
                r.chunk_id,
                r.doc_id,
                r.doc_title,
                r.publisher,
                r.year,
                r.page,
                tuple(r.typologies),
                float(r.score),
            )
            for r in rows
            if r.score is not None
        ]
