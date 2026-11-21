"""SCRUM-307 추가 검토 2 회귀 — ES 200 아님·`_count` 샤드 · NaN cosine · DB 에 없는 후보 · 스냅샷 하나."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest

from aml_ai.shared.config import Settings
from tests.str import rag_eval_v3_hybrid_es as es
from tests.str import rag_eval_v3_hybrid_guard as guard
from tests.str import rag_eval_v3_hybrid_live as live
from tests.str import rag_eval_v3_hybrid_run as run
from tests.str import rag_eval_v3_hybrid_support as hs
from tests.str.test_rag_eval_v3_hybrid_review1 import FakeRetriever, cand_file, prepared

SETTINGS = Settings(ELASTIC_PASSWORD="x")


def _search_body(**over: object) -> bytes:
    body = {"timed_out": False, "_shards": {"total": 1, "failed": 0}, "hits": {"hits": [{"_id": "c1"}]}}
    return json.dumps({**body, **over}).encode()


def _mock(status: int, content: bytes) -> httpx.MockTransport:
    return httpx.MockTransport(lambda r: httpx.Response(status, content=content))


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (200, _search_body(timed_out=True, hits={"hits": []}), "timed_out"),
        (200, _search_body(_shards={"failed": 1}), "shards_failed"),
        (206, _search_body(timed_out=True, _shards={"failed": 1}, hits={"hits": []}), "status_206"),
        (200, b"not json", "body_invalid"),
    ],
)
def test_partial_search_response_stops(status: int, body: bytes, reason: str) -> None:
    with pytest.raises(es.PartialSearch, match=reason):
        es.checked_keyword_search(SETTINGS, _mock(status, body)).search("en", "fan in", 10)


def test_full_search_response_passes() -> None:
    assert es.checked_keyword_search(SETTINGS, _mock(200, _search_body())).search("en", "fan in", 10) == [
        "c1"
    ]


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (200, {"count": 722, "_shards": {"failed": 1}}, "shards_failed"),
        (206, {"count": 722, "_shards": {"failed": 0}}, "status_206"),
        (200, {"count": 722}, "shards_failed"),
    ],
)
def test_es_count_checks_status_and_shards(status: int, body: dict, reason: str) -> None:
    with pytest.raises(es.PartialSearch, match=reason):
        es.es_count(SETTINGS, _mock(status, json.dumps(body).encode()))


def test_es_count_ok() -> None:
    assert es.es_count(SETTINGS, _mock(200, b'{"count": 722, "_shards": {"failed": 0}}')) == 722


def test_nan_cosine_stops_before_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "Retriever", FakeRetriever)
    with pytest.raises(ValueError, match="유한하지 않음"):
        run.search(prepared([["nan"]]), hs.Condition(False, ("a",), True), None)


def test_candidate_missing_from_db_is_refused() -> None:
    a, b = "a" * 64, "b" * 64
    cand = {
        "candidates": {"FAN_IN": [{"chunk_id": a, "db_tagged": True}, {"chunk_id": b, "db_tagged": False}]}
    }
    assert guard.tag_problem(cand, {a: {"FAN_IN"}}).startswith("정답 후보 chunk_id 가 DB 에 없음 1")


@pytest.fixture
def one_snapshot(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    @contextmanager
    def snapshot() -> Iterator[str]:
        seen.append("snapshot")
        yield "S"

    monkeypatch.setattr(live, "snapshot_session", snapshot)
    monkeypatch.setattr(live, "prepare_query", lambda q, *a: prepared([]))
    monkeypatch.setattr(live, "sentence_hashes", lambda p: {})
    return seen


def test_snapshot_recheck_failure_stops_before_search(
    monkeypatch: pytest.MonkeyPatch, one_snapshot: list
) -> None:
    monkeypatch.setattr(guard, "db_problem", lambda s, c, p: ("태그 다름", 722))
    monkeypatch.setattr(live, "search", lambda *a: one_snapshot.append("search") or ([], 0.0))
    with pytest.raises(ValueError, match="스냅샷 재확인 실패"):
        live.evaluate(SETTINGS, cand_file(), {"positions": {}}, dry=True)
    assert one_snapshot == ["snapshot"]


def test_all_searches_share_one_snapshot(monkeypatch: pytest.MonkeyPatch, one_snapshot: list) -> None:
    sessions: set = set()
    monkeypatch.setattr(guard, "db_problem", lambda s, c, p: (None, 722))
    monkeypatch.setattr(live, "search", lambda p, c, s: sessions.add(s) or ([], 0.0))
    monkeypatch.setattr(hs, "verdict", lambda by: {})  # 판정 산식은 다른 테스트 — 여기선 세션만
    live.evaluate(SETTINGS, cand_file(), {"positions": {}}, dry=True)
    assert sessions == {"S"} and one_snapshot == ["snapshot"]
