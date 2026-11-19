"""SCRUM-275 — 빈칸 채우기 fail-open (docs/str/10 "실패하면"). 가짜 후보·임베더·키워드, DB·LLM 0.

키워드 실패 → 벡터만으로 채움 · 추가 임베딩·PG 2차·합치기 실패 → 1차 결과만 · 로그에 값·본문 없음.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aml_ai.str.infrastructure import retriever_fill
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.retriever_fill_support import Calls, Embed, Keyword, facts, install, ref

_FIRST = [ref("t1", 0.41), ref("t2", 0.39)]
_UNFILTERED = {0: [ref("u1", 0.3)], 10: [ref("u1", 0.5)], 11: []}
_COSINE = {"u1": 0.3, "k1": 0.2}


class _LogSpy:
    """retriever_fill.log 자리 — 다른 테스트의 로깅 설정과 무관하게 경고만 모음(test_injection_rag 와 같은 방식)."""

    def __init__(self) -> None:
        self.records: list[tuple[str, dict]] = []

    def warning(self, msg: str, extra: dict | None = None) -> None:
        self.records.append((msg, dict(extra or {})))


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _LogSpy:
    log = _LogSpy()
    monkeypatch.setattr(retriever_fill, "log", log)
    return log


def _retriever(calls: Calls, keyword: Keyword | None, embed: Embed | None = None) -> Retriever:
    return Retriever(
        MagicMock(),
        embed or Embed(calls),
        enabled=True,
        gap_fill=True,
        keyword=keyword,
        release=lambda: calls.order.append("release"),
    )


@pytest.mark.parametrize(
    "reason", ["timeout", "status_401", "status_404", "password_missing", "request_failed"]
)
def test_keyword_failure_falls_back_to_vectors(
    monkeypatch: pytest.MonkeyPatch, spy: _LogSpy, reason: str
) -> None:
    calls = Calls()
    install(monkeypatch, calls, filtered=_FIRST, unfiltered=_UNFILTERED, cosine_a=_COSINE)
    out = _retriever(calls, Keyword(calls, {"en": ["k1"]}, error=reason)).retrieve(facts())
    assert [r.chunk_id for r in out] == ["t1", "t2", "u1"]
    assert spy.records == [("keyword_unavailable", {"reason": reason})]
    assert len(calls.keywords) == 1  # 첫 실패에서 키워드 목록 전부 포기 — 국문은 안 부름


def test_second_embedding_failure_returns_first_pass(monkeypatch: pytest.MonkeyPatch, spy: _LogSpy) -> None:
    calls = Calls()
    install(monkeypatch, calls, filtered=_FIRST, unfiltered=_UNFILTERED, cosine_a=_COSINE)
    out = _retriever(calls, Keyword(calls, {}), embed=Embed(calls, fail_on=2)).retrieve(facts())
    assert out == _FIRST
    assert spy.records == [("rag_fill_failed", {"reason": "RetrievalUnavailable"})]


def test_unfiltered_search_failure_returns_first_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(
        monkeypatch, calls, filtered=_FIRST, unfiltered=_UNFILTERED, cosine_a=_COSINE, fail_unfiltered=True
    )
    assert _retriever(calls, Keyword(calls, {})).retrieve(facts()) == _FIRST


def test_fusion_bug_returns_first_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(monkeypatch, calls, filtered=_FIRST, unfiltered=_UNFILTERED, cosine_a=_COSINE)

    def boom(lists: object) -> object:
        raise ValueError("fusion bug")

    monkeypatch.setattr(retriever_fill, "rrf_fuse", boom)
    assert _retriever(calls, Keyword(calls, {})).retrieve(facts()) == _FIRST


def test_release_failure_returns_first_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = Calls()
    install(monkeypatch, calls, filtered=_FIRST, unfiltered=_UNFILTERED, cosine_a=_COSINE)

    def bad_release() -> None:
        raise RuntimeError("dirty session")

    retriever = Retriever(MagicMock(), Embed(calls), enabled=True, gap_fill=True, release=bad_release)
    assert retriever.retrieve(facts()) == _FIRST
    assert "embed" not in calls.order[1:]  # 반납 못 하면 외부 호출 안 함


def test_logs_have_no_query_or_text(monkeypatch: pytest.MonkeyPatch, spy: _LogSpy) -> None:
    calls = Calls()
    install(
        monkeypatch, calls, filtered=_FIRST, unfiltered=_UNFILTERED, cosine_a=_COSINE, fail_unfiltered=True
    )
    _retriever(calls, Keyword(calls, {}, error="timeout")).retrieve(facts())
    assert [msg for msg, _ in spy.records] == ["keyword_unavailable", "rag_fill_failed"]
    for _msg, extra in spy.records:
        assert set(extra) == {"reason"}  # 이유 낱말만 — 검색어·본문·chunk_id 없음
        assert "funds" not in str(extra) and "순환" not in str(extra)
