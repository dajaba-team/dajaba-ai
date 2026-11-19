"""SCRUM-275 — Retriever 빈칸만 채우기 (docs/str/10 "빈칸만 채우기"). 가짜 후보·임베더·키워드, DB·LLM 0.

규칙 ① 지금 경로 결과 그대로 앞 ② 3건 안 찼을 때만 필터 끈 합치기로 남는 칸 ③ 0건이면 0건.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aml_ai.shared.schemas.common import Typology
from aml_ai.str.domain.constants import RAG_CANDIDATES, RAG_TOP_K
from aml_ai.str.domain.rag_queries import build_queries, build_query
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.retriever_fill_support import Calls, Embed, Keyword, facts, install, ref


def _retriever(calls: Calls, *, keyword: Keyword | None = None, gap_fill: bool = True) -> Retriever:
    return Retriever(
        MagicMock(),
        Embed(calls),
        enabled=True,
        gap_fill=gap_fill,
        keyword=keyword,
        release=lambda: calls.order.append("release"),
    )


def test_default_is_off() -> None:
    assert Retriever(MagicMock(), Embed(Calls()), enabled=True)._gap_fill is False  # noqa: SLF001


def test_full_first_pass_is_returned_as_is_with_no_extra_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    first = [ref("t1", 0.5), ref("t2", 0.4), ref("t3", 0.3)]
    install(monkeypatch, calls, filtered=first, unfiltered={}, cosine_a={})
    out = _retriever(calls, keyword=Keyword(calls, {"en": ["k1"]})).retrieve(facts(Typology.FAN_IN))
    assert out == first
    assert calls.order == ["embed", "pg_filtered"]  # 규칙 1 — release·키워드·추가 임베딩 0


def test_empty_first_pass_stays_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(monkeypatch, calls, filtered=[], unfiltered={0: [ref("u1", 0.6)]}, cosine_a={"u1": 0.6})
    out = _retriever(calls, keyword=Keyword(calls, {"en": ["u1"]})).retrieve(facts(Typology.SCATTER_GATHER))
    assert out == []
    assert calls.order == ["embed", "pg_filtered"]  # 규칙 3 — 채우지 않음


def test_partial_first_pass_keeps_front_and_fills_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    first = [ref("t1", 0.41), ref("t2", 0.39)]
    unfiltered = {
        0: [ref("t1", 0.41), ref("u1", 0.35)],
        10: [ref("u2", 0.7), ref("u1", 0.6)],
        11: [ref("u1", 0.5)],
    }
    install(
        monkeypatch, calls, filtered=first, unfiltered=unfiltered, cosine_a={"u1": 0.35, "u2": 0.2, "k1": 0.1}
    )
    out = _retriever(calls, keyword=Keyword(calls, {"en": ["u1", "k1"]})).retrieve(facts())
    assert out[:2] == first  # 규칙 1 — 순서·chunk_id·score 그대로
    assert [r.chunk_id for r in out] == ["t1", "t2", "u1"]
    assert out[2].score == 0.35  # (a) 기준 cosine — 다른 검색어 cosine(0.6)·RRF 아님
    assert len(out) == RAG_TOP_K


def test_fill_call_order_releases_before_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(
        monkeypatch, calls, filtered=[ref("t1", 0.4)], unfiltered={0: [ref("u1", 0.3)]}, cosine_a={"u1": 0.3}
    )
    _retriever(calls, keyword=Keyword(calls, {"en": ["u1"]})).retrieve(facts())
    first_pg_after = calls.order.index("pg_unfiltered")
    assert calls.order[:3] == ["embed", "pg_filtered", "release"]
    assert "embed" in calls.order[3:first_pg_after] and "keyword" in calls.order[3:first_pg_after]
    assert "release" not in calls.order[3:]  # 외부 호출은 모두 release 뒤, PG 2차 앞


def test_fill_queries_and_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(monkeypatch, calls, filtered=[ref("t1", 0.4)], unfiltered={}, cosine_a={})
    _retriever(calls, keyword=Keyword(calls, {})).retrieve(facts())
    queries = build_queries(facts())
    assert calls.embeds == [[build_query(facts())], [q.text for q in queries[1:]]]  # (a) 다시 안 보냄
    unfiltered = [s for s in calls.searches if not s["filter"]]
    assert [s["limit"] for s in unfiltered] == [RAG_CANDIDATES] * len(queries)
    assert [s["vec"] for s in unfiltered] == [0, 10, 11][: len(queries)]
    assert [k[0] for k in calls.keywords] == ["en", "ko"] and {k[2] for k in calls.keywords} == {
        RAG_CANDIDATES
    }


def test_keyword_only_hit_can_fill(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(
        monkeypatch, calls, filtered=[ref("t1", 0.4), ref("t2", 0.3)], unfiltered={}, cosine_a={"k1": 0.22}
    )
    out = _retriever(calls, keyword=Keyword(calls, {"ko": ["k1"]})).retrieve(facts())
    assert [r.chunk_id for r in out] == ["t1", "t2", "k1"] and out[2].score == 0.22


def test_chunk_missing_in_db_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(monkeypatch, calls, filtered=[ref("t1", 0.4)], unfiltered={}, cosine_a={"k2": 0.2})
    out = _retriever(calls, keyword=Keyword(calls, {"en": ["gone", "k2"]})).retrieve(facts())
    assert [r.chunk_id for r in out] == ["t1", "k2"]  # 색인에만 있는 청크(gone)는 건너뜀


def test_switch_off_is_todays_path(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(
        monkeypatch, calls, filtered=[ref("t1", 0.4)], unfiltered={0: [ref("u1", 0.3)]}, cosine_a={"u1": 0.3}
    )
    out = _retriever(calls, keyword=Keyword(calls, {"en": ["u1"]}), gap_fill=False).retrieve(facts())
    assert [r.chunk_id for r in out] == ["t1"]
    assert calls.order == ["embed", "pg_filtered"]


def test_without_keyword_client_fills_from_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(
        monkeypatch, calls, filtered=[ref("t1", 0.4)], unfiltered={0: [ref("u1", 0.3)]}, cosine_a={"u1": 0.3}
    )
    out = _retriever(calls, keyword=None).retrieve(facts())
    assert [r.chunk_id for r in out] == ["t1", "u1"] and "keyword" not in calls.order
