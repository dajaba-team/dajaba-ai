"""SCRUM-275 ES 키워드 검색 (docs/str/10 "Elasticsearch 연결"). 기존 httpx 로 REST 직접.

검색 응답에서 받는 건 `chunk_id`(= `_id`)·순위뿐 — 본문은 `_source` 에 없음. 실패는 `KeywordUnavailable`
(이유 낱말만, 값 없음) — 호출자(retriever_fill)가 잡아 키워드 목록 없이 진행(fail-open).
"""

from __future__ import annotations

from typing import Protocol

import httpx
from pydantic import BaseModel, Field, ValidationError

from aml_ai.shared.config import Settings
from aml_ai.str.domain.constants_rag_query import KEYWORD_FIELDS


class KeywordUnavailable(Exception):
    """키워드 검색 실패. 메시지 = 이유 낱말(timeout · status_401 · password_missing …) — 값·본문 없음."""

    @property
    def reason(self) -> str:
        return str(self)


class _Hit(BaseModel):
    id: str = Field(alias="_id")


class _Hits(BaseModel):
    hits: list[_Hit]


class _SearchResponse(BaseModel):
    hits: _Hits


class KeywordSearch(Protocol):
    def search(self, lang: str, text: str, size: int) -> list[str]: ...


class HttpKeywordSearch:
    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self._s = settings
        self._transport = transport

    @property
    def timeout_s(self) -> float:
        return self._s.elastic_timeout_s

    def search(self, lang: str, text: str, size: int) -> list[str]:
        """`lang` 청크의 그 언어 본문 필드에서 `match` — 순위대로 `chunk_id`."""
        if not self._s.elastic_password:
            raise KeywordUnavailable("password_missing")
        field = KEYWORD_FIELDS.get(lang)
        if field is None:
            raise KeywordUnavailable("lang_unsupported")
        body = {
            "size": size,
            "_source": False,
            "query": {"bool": {"must": [{"match": {field: text}}], "filter": [{"term": {"lang": lang}}]}},
        }
        url = f"{self._s.elastic_url.rstrip('/')}/{self._s.elastic_index}/_search"
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self._transport) as client:
                response = client.post(
                    url, json=body, auth=(self._s.elastic_username, self._s.elastic_password)
                )
                response.raise_for_status()
                parsed = _SearchResponse.model_validate_json(response.content)
        except httpx.TimeoutException as exc:
            raise KeywordUnavailable("timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise KeywordUnavailable(f"status_{exc.response.status_code}") from exc
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise KeywordUnavailable("request_failed") from exc
        return [hit.id for hit in parsed.hits.hits]


def make_keyword_search(settings: Settings) -> KeywordSearch:
    return HttpKeywordSearch(settings)
