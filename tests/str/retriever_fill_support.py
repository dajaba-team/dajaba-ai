"""SCRUM-275 Retriever 빈칸 채우기 테스트 공용 — 가짜 임베더·키워드·후보·cosine, 호출 순서 기록. DB·LLM 0."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts, Reference
from aml_ai.str.infrastructure.keyword_search import KeywordUnavailable
from aml_ai.str.infrastructure.retriever import Retriever
from tests.conftest import FIXTURES


def facts(typology: Typology = Typology.CYCLE) -> Facts:
    data = json.loads((FIXTURES / "facts_fan_in.json").read_text(encoding="utf-8"))
    data["typology"] = typology.value
    return Facts.model_validate(data)


def ref(cid: str, score: float) -> Reference:
    return Reference(chunk_id=cid, doc_id="d", doc_title="t", page=1, score=score, text="x")


@dataclass
class Calls:
    order: list[str] = field(default_factory=list)
    embeds: list[list[str]] = field(default_factory=list)
    searches: list[dict] = field(default_factory=list)
    keywords: list[tuple[str, str, int]] = field(default_factory=list)
    cosine_ids: list[list[str]] = field(default_factory=list)
    sessions: list[tuple[str, object]] = field(default_factory=list)  # (호출, 넘겨받은 세션) — 2차 격리 확인


class Embed:
    def __init__(self, calls: Calls, fail_on: int | None = None) -> None:
        self.calls = calls
        self.fail_on = fail_on

    def embed(self, texts: list[str]) -> list[list[float]]:
        from aml_ai.shared.errors import RetrievalUnavailable

        self.calls.order.append("embed")
        self.calls.embeds.append(list(texts))
        if self.fail_on is not None and len(self.calls.embeds) == self.fail_on:
            raise RetrievalUnavailable("embedding request failed")
        base = 10 * (len(self.calls.embeds) - 1)  # 첫 호출 (a) = 0, 둘째 호출 (b)(c) = 10, 11
        return [[float(base + i)] for i in range(len(texts))]


class Keyword:
    def __init__(self, calls: Calls, by_lang: dict[str, list[str]], error: str | None = None) -> None:
        self.calls = calls
        self.by_lang = by_lang
        self.error = error

    def search(self, lang: str, text: str, size: int) -> list[str]:
        self.calls.order.append("keyword")
        self.calls.keywords.append((lang, text, size))
        if self.error:
            raise KeywordUnavailable(self.error)
        return self.by_lang.get(lang, [])[:size]


def install(
    monkeypatch: pytest.MonkeyPatch,
    calls: Calls,
    *,
    filtered: list[Reference],
    unfiltered: dict[int, list[Reference]],
    cosine_a: dict[str, float],
    fail_unfiltered: bool = False,
) -> None:
    """`_candidates` 필터 켬 → filtered, 필터 끔 → 벡터 첫 값별 목록. `_cosines` → (a) 기준 cosine."""

    def fake_candidates(self: Retriever, vec: list[float], typology: str | None, *, limit: int,
                        typology_filter: bool, session: object = None) -> list[Reference]:  # fmt: skip
        calls.order.append("pg_filtered" if typology_filter else "pg_unfiltered")
        calls.sessions.append(("pg_filtered" if typology_filter else "pg_unfiltered", session))
        calls.searches.append({"vec": int(vec[0]), "limit": limit, "filter": typology_filter})
        if typology_filter:
            return filtered[:limit]
        if fail_unfiltered:
            from aml_ai.shared.errors import RetrievalUnavailable

            raise RetrievalUnavailable("rag search failed")
        return unfiltered.get(int(vec[0]), [])[:limit]

    def fake_cosines(
        self: Retriever, vec: list[float], chunk_ids: list[str], *, session: object = None
    ) -> list[Reference]:
        calls.order.append("pg_cosine")
        calls.sessions.append(("pg_cosine", session))
        calls.cosine_ids.append(list(chunk_ids))
        assert int(vec[0]) == 0  # 늘 (a) 벡터
        return [ref(c, cosine_a[c]) for c in chunk_ids if c in cosine_a]

    monkeypatch.setattr(Retriever, "_candidates", fake_candidates)
    monkeypatch.setattr(Retriever, "_cosines", fake_cosines)
