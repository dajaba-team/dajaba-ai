"""SCRUM-275 추가 검토 1 high — 채우기 PG 2차는 별도 짧은 세션 (docs/str/10 "실패하면"). DB·LLM 0.

공유(초안) 세션은 release 뒤 다시 안 씀 · 2차 세션 실패는 그 세션만 닫고 1차 결과 반환.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from aml_ai.shared.config import Settings
from aml_ai.str.application.draft_service import DraftService
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.retriever_fill_support import Calls, Embed, Keyword, facts, install, ref

_FIRST = [ref("t1", 0.41), ref("t2", 0.39)]


class _FillSession:
    def __init__(self) -> None:
        self.closed = False


def _factory(opened: list[_FillSession], *, broken: bool = False):
    @contextmanager
    def open_session() -> Iterator[_FillSession]:
        s = _FillSession()
        opened.append(s)
        try:
            if broken:
                raise OperationalError("SELECT 1", {}, Exception("server closed the connection"))
            yield s
        finally:
            s.closed = True

    return open_session


def _retriever(shared: MagicMock, calls: Calls, open_session) -> Retriever:
    return Retriever(shared, Embed(calls), enabled=True, gap_fill=True, keyword=Keyword(calls, {}),
                     release=lambda: calls.order.append("release"), fill_session=open_session)  # fmt: skip


def test_second_pass_uses_fill_session_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, opened, shared = Calls(), [], MagicMock()
    install(monkeypatch, calls, filtered=_FIRST, unfiltered={0: [ref("u1", 0.3)]}, cosine_a={"u1": 0.3})
    out = _retriever(shared, calls, _factory(opened)).retrieve(facts())
    assert [r.chunk_id for r in out] == ["t1", "t2", "u1"]
    assert calls.sessions[0] == ("pg_filtered", None)  # 1차 = 공유 세션(인자 없음 → self._s)
    second = calls.sessions[1:]
    assert second and all(s is opened[0] for _, s in second)  # 2차 = 별도 세션 하나
    assert opened[0].closed is True and len(opened) == 1


def test_broken_fill_session_returns_first_and_leaves_shared_session_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls, opened, shared = Calls(), [], MagicMock()
    install(monkeypatch, calls, filtered=_FIRST, unfiltered={0: [ref("u1", 0.3)]}, cosine_a={"u1": 0.3})
    out = _retriever(shared, calls, _factory(opened, broken=True)).retrieve(facts())
    assert out == _FIRST
    assert opened[0].closed is True
    assert shared.rollback.call_count == 0 and shared.close.call_count == 0  # 초안 세션 손대지 않음
    assert [o for o in calls.order if o.startswith("pg_")] == ["pg_filtered"]


def test_failure_inside_fill_session_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, opened, shared = Calls(), [], MagicMock()
    install(monkeypatch, calls, filtered=_FIRST, unfiltered={}, cosine_a={}, fail_unfiltered=True)
    assert _retriever(shared, calls, _factory(opened)).retrieve(facts()) == _FIRST
    assert opened[0].closed is True and shared.rollback.call_count == 0


def test_draft_service_injects_separate_session_on_same_engine() -> None:
    shared = MagicMock()
    settings = Settings(_env_file=None, RAG_ENABLED=True, RAG_GAP_FILL_ENABLED=True)
    retriever = DraftService.build(shared, settings).retriever
    fill = retriever._fill_session()  # noqa: SLF001
    assert fill is not shared and fill.get_bind() is shared.get_bind.return_value
    fill.close()
