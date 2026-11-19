"""SCRUM-275 — ES 색인 만들기 (docs/str/10 "Elasticsearch 연결"). httpx 가짜 전송, DB·네트워크 0.

본문은 역색인에만(`_source` 제외) · 언어별 분석기 · 지우고 다시 만듦 · 개수 확인.
"""

from __future__ import annotations

import json

import httpx
import pytest

from aml_ai.str.infrastructure.keyword_index import ChunkRow, index_body, index_doc, rebuild

_ROWS = [
    ChunkRow("c1", "fatf-pml-2018", 3, "en", ["CYCLE"], "english body"),
    ChunkRow("c2", "fincen-msb-ko-2007", 7, "ko", [], "국문 본문"),
]


def test_index_body_excludes_text_from_source_and_sets_analyzers() -> None:
    body = index_body()
    assert set(body["mappings"]["_source"]["excludes"]) == {"text_en", "text_ko"}
    props = body["mappings"]["properties"]
    assert props["text_en"] == {"type": "text", "analyzer": "english"}
    assert props["text_ko"] == {"type": "text", "analyzer": "cjk"}
    for name in ("chunk_id", "doc_id", "lang", "typologies"):
        assert props[name] == {"type": "keyword"}
    assert props["page"] == {"type": "integer"}


def test_index_doc_fills_only_its_language_field() -> None:
    assert index_doc(_ROWS[0]) == {
        "chunk_id": "c1", "doc_id": "fatf-pml-2018", "page": 3, "lang": "en", "typologies": ["CYCLE"],
        "text_en": "english body",
    }  # fmt: skip
    assert "text_en" not in index_doc(_ROWS[1]) and index_doc(_ROWS[1])["text_ko"] == "국문 본문"


def test_index_doc_rejects_unknown_language() -> None:
    with pytest.raises(ValueError, match="lang"):
        index_doc(ChunkRow("c3", "d", 1, "fr", [], "x"))


class _Es:
    def __init__(self, count: int, delete_status: int = 200) -> None:
        self.calls: list[tuple[str, str]] = []
        self.bulk_lines: list[dict] = []
        self.count = count
        self.delete_status = delete_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.method == "DELETE":
            return httpx.Response(self.delete_status, json={})
        if request.url.path.endswith("/_bulk"):
            assert request.headers["content-type"] == "application/x-ndjson"
            self.bulk_lines += [json.loads(line) for line in request.content.decode().splitlines() if line]
            return httpx.Response(200, json={"errors": False, "items": []})
        if request.url.path.endswith("/_count"):
            return httpx.Response(200, json={"count": self.count})
        return httpx.Response(200, json={"acknowledged": True})


def _run(es: _Es) -> int:
    with httpx.Client(base_url="http://es:9200", transport=httpx.MockTransport(es)) as client:
        return rebuild(client, "idx", _ROWS)


def test_rebuild_deletes_creates_bulks_refreshes_and_counts() -> None:
    es = _Es(count=2)
    assert _run(es) == 2
    assert [c[0] for c in es.calls] == ["DELETE", "PUT", "POST", "POST", "GET"]
    assert es.calls[1] == ("PUT", "/idx") and es.calls[2] == ("POST", "/idx/_bulk")
    assert es.calls[3] == ("POST", "/idx/_refresh") and es.calls[4] == ("GET", "/idx/_count")
    assert es.bulk_lines[0] == {"index": {"_id": "c1"}} and es.bulk_lines[2] == {"index": {"_id": "c2"}}


def test_rebuild_ignores_missing_index_on_delete() -> None:
    assert _run(_Es(count=2, delete_status=404)) == 2


def test_rebuild_returns_es_count_even_when_different() -> None:
    assert _run(_Es(count=1)) == 1  # 비교·종료 코드는 도구가


def test_bulk_errors_raise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/_bulk"):
            return httpx.Response(200, json={"errors": True, "items": []})
        return httpx.Response(200, json={"count": 0})

    transport = httpx.MockTransport(handler)
    with (
        httpx.Client(base_url="http://es:9200", transport=transport) as client,
        pytest.raises(RuntimeError, match="bulk"),
    ):
        rebuild(client, "idx", _ROWS)
