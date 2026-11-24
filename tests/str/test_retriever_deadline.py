"""SCRUM-413 초안 참고자료(벡터) 조회 시간 제한 — 가짜 세션·시계 (docs/str/03 초안 6 · 10). DB·임베딩 0.

`retrieve(facts, deadline=…)` — 벡터 조회(`_candidates`·`_cosines`)마다 같은 트랜잭션에 남은 ms.
남은 ≤ 0 이면 벡터 SQL 0·`RetrievalUnavailable` · deadline 없음이면 지금 그대로(설정 SQL 0).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.schemas.common import Typology
from aml_ai.str.domain.constants_rag_query import REFERENCE_TABLE
from aml_ai.str.infrastructure.retriever import Retriever
from tests.shared.db_deadline_support import SET_CONFIG, Events, FakeClock, FakeSession
from tests.str.retriever_fill_support import facts

T0 = 500.0


class _Embed:
    model = "test-embed"

    def __init__(self, on_embed=None) -> None:  # type: ignore[no-untyped-def]
        self.on_embed = on_embed
        self.calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self.on_embed is not None:
            self.on_embed(self.calls)
        return [[0.1, 0.2] for _ in texts]


def _row(cid: str, score: float) -> SimpleNamespace:
    return SimpleNamespace(chunk_id=cid, doc_id="d", doc_title="t", page=1, score=score, text="x")


ROWS = [_row("c1", 0.9), _row("c2", 0.8)]


def _vector_sqls(ev: Events) -> list[str]:
    return [s for s in ev.sqls() if REFERENCE_TABLE in s]


def _retriever(session: FakeSession, clock, **kw) -> Retriever:  # type: ignore[no-untyped-def]
    return Retriever(session, _Embed(kw.pop("on_embed", None)), enabled=True, clock=clock, **kw)  # type: ignore[arg-type]


def test_deadline_sets_remaining_ms_before_vector_sql() -> None:
    ev = Events()
    out = _retriever(FakeSession(ev, {REFERENCE_TABLE: ROWS}), FakeClock(ev, T0)).retrieve(
        facts(), deadline=T0 + 0.3
    )
    sqls = ev.sqls()
    first_set = next(i for i, s in enumerate(sqls) if SET_CONFIG in s)
    first_vec = next(i for i, s in enumerate(sqls) if REFERENCE_TABLE in s)
    assert first_set < first_vec
    assert any(isinstance(p, dict) and "300ms" in p.values() for p in ev.params())
    assert [r.chunk_id for r in out] == ["c1", "c2"]


def test_results_same_with_and_without_deadline() -> None:
    ev_a, ev_b = Events(), Events()
    a = _retriever(FakeSession(ev_a, {REFERENCE_TABLE: ROWS}), FakeClock(ev_a, T0)).retrieve(facts())
    b = _retriever(FakeSession(ev_b, {REFERENCE_TABLE: ROWS}), FakeClock(ev_b, T0)).retrieve(
        facts(), deadline=T0 + 30
    )
    assert a == b


def test_no_deadline_runs_no_set_sql() -> None:
    """하네스·평가 도구 경로 — 지금 동작 그대로."""
    ev = Events()
    _retriever(FakeSession(ev, {REFERENCE_TABLE: ROWS}), FakeClock(ev, T0)).retrieve(facts())
    assert not any(SET_CONFIG in s for s in ev.sqls())


@pytest.mark.parametrize("deadline", [T0, T0 - 1.0])
def test_expired_deadline_runs_no_vector_sql(deadline: float) -> None:
    ev = Events()
    with pytest.raises(RetrievalUnavailable):
        _retriever(FakeSession(ev, {REFERENCE_TABLE: ROWS}), FakeClock(ev, T0)).retrieve(
            facts(), deadline=deadline
        )
    assert _vector_sqls(ev) == []


def test_multi_query_path_also_bounded() -> None:
    ev = Events()
    with pytest.raises(RetrievalUnavailable):
        _retriever(FakeSession(ev, {REFERENCE_TABLE: ROWS}), FakeClock(ev, T0), multi_query=True).retrieve(
            facts(Typology.FAN_IN), deadline=T0
        )
    assert _vector_sqls(ev) == []


# ── 채우기 2차(fill_session) — 같은 마감, 실패는 지금처럼 1차 결과(fail-open) ──


def _fill_factory(events: Events, rows: list[SimpleNamespace]):  # type: ignore[no-untyped-def]
    opened: list[FakeSession] = []

    @contextmanager
    def open_session() -> Iterator[FakeSession]:
        s = FakeSession(events, {REFERENCE_TABLE: rows})
        opened.append(s)
        yield s

    return open_session, opened


def test_fill_second_pass_bounds_every_vector_query() -> None:
    shared_ev, fill_ev = Events(), Events()
    open_session, opened = _fill_factory(fill_ev, [_row("u1", 0.7)])
    r = _retriever(
        FakeSession(shared_ev, {REFERENCE_TABLE: [_row("c1", 0.9)]}),
        FakeClock(shared_ev, T0),
        gap_fill=True,
        fill_session=open_session,
    )
    out = r.retrieve(facts(), deadline=T0 + 30)
    assert opened and [x.chunk_id for x in out][0] == "c1"
    sqls = fill_ev.sqls()
    vec = [i for i, s in enumerate(sqls) if REFERENCE_TABLE in s]
    sets = [i for i, s in enumerate(sqls) if SET_CONFIG in s]
    assert vec and len(sets) == len(vec)  # _candidates·_cosines 마다 한 번
    assert all(any(s < v for s in sets) for v in vec)


def test_fill_expired_at_second_pass_returns_first_without_vector_sql() -> None:
    shared_ev, fill_ev = Events(), Events()
    clock = FakeClock(shared_ev, T0)
    open_session, _ = _fill_factory(fill_ev, [_row("u1", 0.7)])

    def expire(n: int) -> None:  # 두 번째 임베딩(채우기 질의) 때 마감이 지남
        if n >= 2:
            clock.now = T0 + 100

    r = _retriever(
        FakeSession(shared_ev, {REFERENCE_TABLE: [_row("c1", 0.9)]}),
        clock,
        gap_fill=True,
        fill_session=open_session,
        on_embed=expire,
    )
    out = r.retrieve(facts(), deadline=T0 + 30)
    assert [x.chunk_id for x in out] == ["c1"]
    assert _vector_sqls(fill_ev) == []
