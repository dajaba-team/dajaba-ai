"""SCRUM-275 ES 키워드 색인 만들기 — `ai.reference_chunks` → Elasticsearch (docs/str/10 "Elasticsearch 연결").

원본은 PostgreSQL, ES 에는 검색 색인만(본문은 `_source` 제외). 색인을 지우고 다시 만든 뒤 문서 수 = DB 행 수인지
확인 — 다르면 종료 코드 1. ES 는 호스트 포트가 없어 AI 컨테이너 안에서 실행 — 이미지에는 서비스 코드만 있으므로
(SCRUM-256) tools 를 읽기 전용으로 붙임:
    docker compose run --rm -v "$PWD/tools:/app/tools:ro" -e PYTHONPATH=/app/src:/app ai python -m tools.index_es
출력은 개수만(본문·비밀값 없음).
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.db import get_engine
from aml_ai.str.domain.constants_rag_query import ES_ADMIN_TIMEOUT_S
from aml_ai.str.infrastructure.keyword_index import ChunkRow, rebuild


def load_rows() -> list[ChunkRow]:
    with Session(get_engine()) as session:
        rows = session.execute(
            text(
                "SELECT chunk_id, doc_id, page, lang, typologies, text FROM ai.reference_chunks ORDER BY chunk_id"
            )
        ).all()
    return [ChunkRow(r.chunk_id, r.doc_id, r.page, r.lang, list(r.typologies), r.text) for r in rows]


def run(
    settings: Settings,
    rows: list[ChunkRow],
    *,
    transport: httpx.BaseTransport | None = None,
    out: Callable[[str], None] = print,
) -> int:
    if not settings.elastic_password:
        out("ELASTIC_PASSWORD 빈 값 — 색인 안 함")
        return 1
    with httpx.Client(
        base_url=settings.elastic_url.rstrip("/"),
        auth=(settings.elastic_username, settings.elastic_password),
        timeout=ES_ADMIN_TIMEOUT_S,
        transport=transport,
    ) as client:
        counted = rebuild(client, settings.elastic_index, rows)
    out(f"index={settings.elastic_index} db_rows={len(rows)} es_docs={counted}")
    if counted != len(rows):
        out("개수 다름 — 색인 확인 필요")
        return 1
    return 0


def main() -> None:
    settings = get_settings()
    sys.exit(run(settings, load_rows()))


if __name__ == "__main__":
    main()
