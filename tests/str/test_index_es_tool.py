"""SCRUM-275 — tools/index_es.py (docs/str/10 "Elasticsearch 연결"). httpx 가짜 전송, DB·네트워크 0."""

from __future__ import annotations

import httpx
from tools.index_es import run

from aml_ai.shared.config import Settings
from aml_ai.str.infrastructure.keyword_index import ChunkRow

_SECRET = "pw-should-not-print"
_ROWS = [ChunkRow("c1", "d", 1, "en", [], "body"), ChunkRow("c2", "d", 2, "ko", [], "본문")]


def _es(count: int) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/_count"):
            return httpx.Response(200, json={"count": count})
        if request.url.path.endswith("/_bulk"):
            return httpx.Response(200, json={"errors": False})
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler)


def _settings(password: str = _SECRET) -> Settings:
    return Settings(_env_file=None, ELASTIC_PASSWORD=password, ELASTIC_URL="http://es:9200")


def test_match_exits_zero_and_prints_counts_only() -> None:
    lines: list[str] = []
    assert run(_settings(), _ROWS, transport=_es(2), out=lines.append) == 0
    assert lines == ["index=ai_reference_chunks_v1 db_rows=2 es_docs=2"]


def test_count_mismatch_exits_one() -> None:
    lines: list[str] = []
    assert run(_settings(), _ROWS, transport=_es(1), out=lines.append) == 1
    assert _SECRET not in " ".join(lines) and "body" not in " ".join(lines)


def test_empty_password_exits_one_without_calls() -> None:
    called: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(1)
        return httpx.Response(200, json={})

    assert run(_settings(""), _ROWS, transport=httpx.MockTransport(handler), out=lambda _: None) == 1
    assert called == []
