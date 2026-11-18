"""SCRUM-146 — Retriever 다중 질의 스위치 (docs/str/10 "다중 질의·합치기"). LLM·DB 0(후보 조회는 가짜).

끔(기본): 임베딩 1회·검색 1회·질의 = build_query · MIN_SIMILARITY 지금 그대로.
켬: 임베딩 1회(배치 N) · 검색 N회(후보 RAG_CANDIDATES) · RRF 뒤 상위 k · score = 최대 cosine · MIN_SIMILARITY 는 합친 뒤.
`_candidates(vec, typology, *, limit, typology_filter)` = SQL 결과 그대로(MIN_SIMILARITY 안 거름).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from aml_ai.shared.schemas.str import Facts, Reference
from aml_ai.str.domain.constants import RAG_CANDIDATES, RAG_MULTI_QUERY, RAG_TOP_K
from aml_ai.str.domain.rag_queries import build_queries, build_query
from aml_ai.str.infrastructure import retriever as retriever_mod
from aml_ai.str.infrastructure.retriever import Retriever
from tests.conftest import FIXTURES


def _facts() -> Facts:
    return Facts.model_validate(json.loads((FIXTURES / "facts_fan_in.json").read_text(encoding="utf-8")))


class _Embed:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(i)] for i in range(len(texts))]  # 검색어 순서 = 벡터 첫 값


def _ref(cid: str, score: float) -> Reference:
    return Reference(chunk_id=cid, doc_id="d", doc_title="t", page=1, score=score, text="x")


def _install(monkeypatch: pytest.MonkeyPatch, by_vec: dict[int, list[Reference]]) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []

    def fake(self: Retriever, vec: list[float], typology: str | None, *, limit: int,
             typology_filter: bool) -> list[Reference]:  # fmt: skip
        seen.append({"vec": int(vec[0]), "typology": typology, "limit": limit, "filter": typology_filter})
        return by_vec[int(vec[0])][:limit]

    monkeypatch.setattr(Retriever, "_candidates", fake)
    return seen


def test_switch_default_off() -> None:
    assert RAG_MULTI_QUERY is False
    assert Retriever(MagicMock(), _Embed(), enabled=True)._multi_query is False  # noqa: SLF001


def test_off_is_one_embed_one_search_with_todays_query(monkeypatch: pytest.MonkeyPatch) -> None:
    emb = _Embed()
    seen = _install(monkeypatch, {0: [_ref("a", 0.9), _ref("b", 0.2)]})
    monkeypatch.setattr(retriever_mod, "MIN_SIMILARITY", 0.5)
    out = Retriever(MagicMock(), emb, enabled=True).retrieve(_facts())
    assert emb.calls == [[build_query(_facts())]]
    assert seen == [{"vec": 0, "typology": "FAN_IN", "limit": RAG_TOP_K, "filter": True}]
    assert [r.chunk_id for r in out] == ["a"]  # MIN_SIMILARITY 지금 뜻 그대로


def test_on_is_one_batch_embed_and_n_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    emb = _Embed()
    by_vec = {0: [_ref("x", 0.6), _ref("y", 0.5)], 1: [_ref("y", 0.9), _ref("z", 0.4)], 2: [_ref("y", 0.3)]}
    seen = _install(monkeypatch, by_vec)
    out = Retriever(MagicMock(), emb, enabled=True, multi_query=True).retrieve(_facts())
    assert emb.calls == [[q.text for q in build_queries(_facts())]]  # 한 번에
    assert [s["limit"] for s in seen] == [RAG_CANDIDATES] * 3 and [s["vec"] for s in seen] == [0, 1, 2]
    assert [r.chunk_id for r in out] == ["y", "x", "z"][:RAG_TOP_K]
    assert out[0].score == 0.9  # 최대 cosine — RRF 아님


def test_on_min_similarity_after_fusion_by_max_cosine(monkeypatch: pytest.MonkeyPatch) -> None:
    by_vec = {0: [_ref("x", 0.2)], 1: [_ref("x", 0.7), _ref("w", 0.3)], 2: []}
    _install(monkeypatch, by_vec)
    monkeypatch.setattr(retriever_mod, "MIN_SIMILARITY", 0.5)
    out = Retriever(MagicMock(), _Embed(), enabled=True, multi_query=True).retrieve(_facts())
    assert [(r.chunk_id, r.score) for r in out] == [("x", 0.7)]


@pytest.mark.parametrize("multi", [False, True])
def test_typology_filter_passes_through(monkeypatch: pytest.MonkeyPatch, multi: bool) -> None:
    seen = _install(monkeypatch, {0: [], 1: [], 2: []})
    Retriever(MagicMock(), _Embed(), enabled=True, multi_query=multi, typology_filter=False).retrieve(
        _facts()
    )
    assert seen and {s["filter"] for s in seen} == {False}


@pytest.mark.parametrize("multi", [False, True])
def test_no_typology_or_disabled_makes_no_calls(monkeypatch: pytest.MonkeyPatch, multi: bool) -> None:
    emb = _Embed()
    seen = _install(monkeypatch, {})
    assert (
        Retriever(MagicMock(), emb, enabled=True, multi_query=multi).retrieve(
            _facts().model_copy(update={"typology": None})
        )
        == []
    )
    assert Retriever(MagicMock(), emb, enabled=False, multi_query=multi).retrieve(_facts()) == []
    assert emb.calls == [] and seen == []


def test_query_kinds_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    emb = _Embed()
    _install(monkeypatch, {0: [], 1: []})
    Retriever(MagicMock(), emb, enabled=True, multi_query=True, query_kinds=("a", "c")).retrieve(_facts())
    assert emb.calls == [[q.text for q in build_queries(_facts(), ("a", "c"))]]
