"""검색 SQL — 지금 표·청크 맥락 새 표가 **같은 모양**(SCRUM-308-3, str/10 "청크 맥락"). 표 이름은 허용 목록만.

같은 임베딩 모델 행만(추가 검토 5 — 차원이 같은 다른 모델 벡터와 섞지 않음) · 바깥 정렬 `거리, chunk_id`(동점 — LIMIT 3 =
LIMIT 10 앞 셋, 추가 검토 6).
"""

from __future__ import annotations

from sqlalchemy import TextClause, text

from aml_ai.str.domain.constants_rag_query import REFERENCE_TABLE, REFERENCE_TABLES


def _checked(table: str) -> str:
    if table not in REFERENCE_TABLES:
        raise ValueError("unknown reference table")
    return table


def candidates_sql(table: str, *, typology_filter: bool) -> TextClause:
    predicate = "WHERE embedding_model = :model " + (
        "AND typologies @> ARRAY[:ty]::text[] " if typology_filter else ""
    )
    return text(
        "WITH r AS MATERIALIZED ("
        "  SELECT chunk_id, doc_id, doc_title, page, text, "
        "         embedding <=> CAST(:vec AS vector) AS d "
        f"  FROM {_checked(table)} " + predicate + "  ORDER BY embedding <=> CAST(:vec AS vector) "
        "  LIMIT :cand"
        ") "
        "SELECT chunk_id, doc_id, doc_title, page, text, 1 - d AS score "
        "FROM r ORDER BY d + 0, chunk_id LIMIT :k"
    )


def cosines_sql(table: str) -> TextClause:
    return text(
        "SELECT chunk_id, doc_id, doc_title, page, text, "
        "       1 - (embedding <=> CAST(:vec AS vector)) AS score "
        f"FROM {_checked(table)} WHERE chunk_id = ANY(:ids) AND embedding_model = :model"
    )


def reference_search_sql() -> TextClause:
    """SCRUM-309 참고 사례 검색 — 지금 표 · 같은 모델 · 유형 OR 필터 · 바깥 정렬 `거리, chunk_id`. 구절용 본문도 읽음."""
    return text(
        "WITH r AS MATERIALIZED ("
        "  SELECT chunk_id, doc_id, doc_title, publisher, year, page, typologies, text, "
        "         embedding <=> CAST(:vec AS vector) AS d "
        f"  FROM {REFERENCE_TABLE} WHERE embedding_model = :model AND typologies && CAST(:tys AS text[]) "
        "  ORDER BY embedding <=> CAST(:vec AS vector) "
        "  LIMIT :cand"
        ") "
        "SELECT chunk_id, doc_id, doc_title, publisher, year, page, typologies, text, 1 - d AS score "
        "FROM r ORDER BY d + 0, chunk_id"
    )
