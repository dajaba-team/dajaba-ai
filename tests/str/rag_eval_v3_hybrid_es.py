"""SCRUM-307 평가용 ES 응답 검사 (추가 검토 1·2 — src `KeywordSearch` 는 안 고치고 transport 로 끼움).

`_search`·`_count` 응답은 HTTP 200 만 받고 `_shards.failed == 0` 이어야 하며, `_search` 는 `timed_out == false` 도.
아니면 `PartialSearch` — 평가는 빈 목록·부분 개수를 성공으로 세지 않고 멈춤(결과 파일 안 씀).
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from aml_ai.shared.config import Settings
from aml_ai.str.infrastructure.keyword_search import HttpKeywordSearch, KeywordSearch

ES_TIMEOUT_S = 5.0
CHECKED_PATHS = ("/_search", "/_count")


class PartialSearch(RuntimeError):
    """ES 부분 응답(200 아님 · 시간 초과 · 샤드 실패) — 이유 낱말만."""


def es_reason(path: str, status: int, body: dict[str, Any] | None) -> str | None:
    """검사 대상 경로면 문제 이유, 아니면 None."""
    if not path.endswith(CHECKED_PATHS):
        return None
    if status != httpx.codes.OK:
        return f"status_{status}"
    if body is None:
        return "body_invalid"
    if path.endswith("/_search") and body.get("timed_out") is not False:
        return "timed_out"
    shards = body.get("_shards")
    if not isinstance(shards, dict) or shards.get("failed") != 0:
        return "shards_failed"
    return None


def _body(response: httpx.Response) -> dict[str, Any] | None:
    try:
        body = json.loads(response.content)
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


class CheckedTransport(httpx.BaseTransport):
    """응답 본문을 먼저 읽어 `es_reason` 이 있으면 `PartialSearch`.

    `HttpKeywordSearch` 는 호출마다 Client 를 닫아 transport 도 닫히므로, 기본은 요청마다 새 HTTPTransport.
    """

    def __init__(self, inner: httpx.BaseTransport | None = None) -> None:
        self._inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if self._inner is not None:
            return self._checked(request, self._inner.handle_request(request))
        with httpx.HTTPTransport() as transport:
            return self._checked(request, transport.handle_request(request))

    @staticmethod
    def _checked(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        response.read()
        if reason := es_reason(request.url.path, response.status_code, _body(response)):
            raise PartialSearch(reason)
        return response


def checked_keyword_search(settings: Settings, inner: httpx.BaseTransport | None = None) -> KeywordSearch:
    return HttpKeywordSearch(settings, transport=CheckedTransport(inner))


def es_count(settings: Settings, inner: httpx.BaseTransport | None = None) -> int:
    """읽기 전용 `_count` — 200·샤드 실패 0 이 아니면 `PartialSearch`(fail-open 없음)."""
    url = f"{settings.elastic_url.rstrip('/')}/{settings.elastic_index}/_count"
    auth = (settings.elastic_username, settings.elastic_password)
    with httpx.Client(transport=CheckedTransport(inner), auth=auth, timeout=ES_TIMEOUT_S) as client:
        return int(client.get(url).json()["count"])
