"""SCRUM-275 — ES 키워드 검색 클라이언트 (docs/str/10 "Elasticsearch 연결"). httpx 가짜 전송, 네트워크 0."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from aml_ai.shared.config import Settings
from aml_ai.str.infrastructure.keyword_search import HttpKeywordSearch, KeywordUnavailable

_SECRET = "s3cr3t-value"


def _settings(**over: object) -> Settings:
    base = {"ELASTIC_PASSWORD": _SECRET, "ELASTIC_URL": "http://es:9200", "ELASTIC_INDEX": "idx"}
    return Settings(_env_file=None, **{**base, **over})


def _client(handler, **over: object) -> HttpKeywordSearch:
    return HttpKeywordSearch(_settings(**over), transport=httpx.MockTransport(handler))


def _hits(*ids: str) -> httpx.Response:
    return httpx.Response(200, json={"hits": {"hits": [{"_id": i, "_score": 1.0} for i in ids]}})


def test_search_request_shape_and_ids() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _hits("c1", "c2")

    assert _client(handler).search("en", "funds return", 10) == ["c1", "c2"]
    req = seen[0]
    assert req.method == "POST" and str(req.url) == "http://es:9200/idx/_search"
    assert req.headers["authorization"].startswith("Basic ")
    body = json.loads(req.content)
    assert body["size"] == 10 and body["_source"] is False
    assert body["query"]["bool"]["must"] == [{"match": {"text_en": "funds return"}}]
    assert body["query"]["bool"]["filter"] == [{"term": {"lang": "en"}}]


def test_korean_goes_to_korean_field() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return _hits()

    _client(handler).search("ko", "순환 거래", 5)
    assert seen[0]["query"]["bool"]["must"] == [{"match": {"text_ko": "순환 거래"}}]
    assert seen[0]["query"]["bool"]["filter"] == [{"term": {"lang": "ko"}}]


@pytest.mark.parametrize(
    ("status", "reason"), [(401, "status_401"), (404, "status_404"), (500, "status_500")]
)
def test_http_errors_become_keyword_unavailable(status: int, reason: str) -> None:
    with pytest.raises(KeywordUnavailable, match=reason):
        _client(lambda r: httpx.Response(status, json={})).search("en", "x", 3)


def test_timeout_is_keyword_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(KeywordUnavailable, match="timeout"):
        _client(handler).search("en", "x", 3)


def test_connect_error_is_keyword_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(KeywordUnavailable, match="request_failed"):
        _client(handler).search("en", "x", 3)


def test_bad_body_is_keyword_unavailable() -> None:
    with pytest.raises(KeywordUnavailable, match="request_failed"):
        _client(lambda r: httpx.Response(200, content=b"not json")).search("en", "x", 3)


def test_empty_password_never_calls_es() -> None:
    called: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(1)
        return _hits()

    with pytest.raises(KeywordUnavailable, match="password_missing"):
        _client(handler, ELASTIC_PASSWORD="").search("en", "x", 3)
    assert called == []


def test_unknown_language_never_calls_es() -> None:
    with pytest.raises(KeywordUnavailable, match="lang"):
        _client(lambda r: _hits()).search("fr", "x", 3)


def test_timeout_setting_is_used() -> None:
    client = _client(lambda r: _hits(), ELASTIC_TIMEOUT_S=0.25)
    assert client.timeout_s == 0.25


def test_password_not_in_repr_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG), pytest.raises(KeywordUnavailable):
        _client(lambda r: httpx.Response(401, json={})).search("en", "x", 3)
    assert _SECRET not in repr(_settings())
    assert _SECRET not in caplog.text
