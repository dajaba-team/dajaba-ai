"""SCRUM-275 ES 색인 만들기 (docs/str/10 "Elasticsearch 연결"). 원본은 PostgreSQL, ES 에는 검색 색인만.

본문 필드(`text_en`·`text_ko`)는 `_source` 에서 빼 역색인에만 — ES 에 원문을 저장하지 않음. 색인을 지우고
다시 만든 뒤 `_bulk` → `_refresh` → `_count`. 개수 비교·종료 코드는 도구(`tools/index_es.py`)가.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx

from aml_ai.str.domain.constants_rag_query import ES_BULK_BATCH, KEYWORD_ANALYZERS, KEYWORD_FIELDS

_NOT_FOUND = 404


@dataclass(frozen=True)
class ChunkRow:
    chunk_id: str
    doc_id: str
    page: int
    lang: str
    typologies: list[str]
    text: str


def index_body() -> dict:
    text_fields = {
        KEYWORD_FIELDS[lang]: {"type": "text", "analyzer": KEYWORD_ANALYZERS[lang]} for lang in KEYWORD_FIELDS
    }
    keywords = {name: {"type": "keyword"} for name in ("chunk_id", "doc_id", "lang", "typologies")}
    return {
        "settings": {"number_of_shards": 1, "number_of_replicas": 0},
        "mappings": {
            "_source": {"excludes": sorted(text_fields)},
            "properties": {**keywords, "page": {"type": "integer"}, **text_fields},
        },
    }


def index_doc(row: ChunkRow) -> dict:
    field = KEYWORD_FIELDS.get(row.lang)
    if field is None:
        raise ValueError(f"lang unsupported: {row.chunk_id}")
    return {
        "chunk_id": row.chunk_id,
        "doc_id": row.doc_id,
        "page": row.page,
        "lang": row.lang,
        "typologies": list(row.typologies),
        field: row.text,
    }


def rebuild(client: httpx.Client, index: str, rows: list[ChunkRow]) -> int:
    """색인을 지우고(없으면 그냥) 다시 만들어 `rows` 를 넣음. ES 가 센 문서 수를 돌려줌."""
    deleted = client.delete(f"/{index}")
    if deleted.status_code != _NOT_FOUND:
        deleted.raise_for_status()
    client.put(f"/{index}", json=index_body()).raise_for_status()
    for start in range(0, len(rows), ES_BULK_BATCH):
        _bulk(client, index, rows[start : start + ES_BULK_BATCH])
    client.post(f"/{index}/_refresh").raise_for_status()
    counted = client.get(f"/{index}/_count")
    counted.raise_for_status()
    return int(counted.json()["count"])


def _bulk(client: httpx.Client, index: str, rows: list[ChunkRow]) -> None:
    lines: list[str] = []
    for row in rows:
        lines.append(json.dumps({"index": {"_id": row.chunk_id}}))
        lines.append(json.dumps(index_doc(row), ensure_ascii=False))
    response = client.post(
        f"/{index}/_bulk",
        content=("\n".join(lines) + "\n").encode(),
        headers={"Content-Type": "application/x-ndjson"},
    )
    response.raise_for_status()
    if response.json().get("errors"):
        raise RuntimeError("bulk index errors")
