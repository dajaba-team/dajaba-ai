"""SCRUM-309 추가 검토 3 회귀 (임베딩·저장소 마감) — 임베딩 절대 마감(루프 쪽 확인) · 설정 왕복 뒤 마감."""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager

import httpx
import pytest

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmUnavailable
from aml_ai.str.infrastructure import reference_embedding as re_mod
from aml_ai.str.infrastructure import reference_search_runtime as runtime
from aml_ai.str.infrastructure.reference_search_repository import ReferenceSearchRepository

KEYED = {"LLM_API_KEY": "k", "EMBEDDING_MODEL": "emb", "EMBEDDING_DIM": 2}


# --- M3 임베딩 절대 마감 ---------------------------------------------------------------------


def _counting() -> tuple[httpx.MockTransport, list[int]]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"model": "emb", "data": [{"embedding": [0.1, 0.2], "index": 0}]})

    return httpx.MockTransport(handler), calls


def test_post_past_deadline_sends_nothing() -> None:
    transport, calls = _counting()
    s = Settings(_env_file=None, **KEYED)
    with pytest.raises(LlmUnavailable):
        asyncio.run(re_mod._post(s, "q", transport, time.monotonic() - 0.01))  # noqa: SLF001
    assert calls == []


def test_blocked_loop_expired_request_never_sent() -> None:
    transport, calls = _counting()
    s = Settings(_env_file=None, **KEYED)

    async def block() -> None:
        time.sleep(0.2)  # 루프를 잠깐 막음

    blocker = runtime.submit(block())
    started = time.monotonic()
    with pytest.raises(LlmUnavailable):
        re_mod.embed_within(s, "q", started + 0.05, transport=transport)
    assert time.monotonic() - started < 0.15  # 호출자가 먼저 502
    blocker.result(timeout=1)
    runtime.submit(asyncio.sleep(0.05)).result(timeout=1)  # 루프가 풀린 뒤 남은 작업이 돌 시간
    assert calls == []


def test_embed_past_deadline_is_502_without_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime, "submit", lambda c: pytest.fail("submitted"))
    with pytest.raises(LlmUnavailable):
        re_mod.embed_within(Settings(_env_file=None, **KEYED), "q", time.monotonic() - 0.01)


# --- M4 설정 왕복 뒤 마감 --------------------------------------------------------------------


class _Session:
    def __init__(self) -> None:
        self.seen: list[str] = []

    @contextmanager
    def begin_nested(self):  # noqa: ANN202
        yield

    def execute(self, stmt, params=None):  # noqa: ANN001, ANN201
        self.seen.append(str(stmt))
        if "set_config" in str(stmt):
            time.sleep(0.14)  # 설정 응답이 140ms 뒤


def test_set_config_round_trip_past_deadline_skips_search() -> None:
    s = _Session()
    with pytest.raises(LlmUnavailable):
        ReferenceSearchRepository(s).search(  # type: ignore[arg-type]
            [1.0], ["FAN_IN"], "emb", deadline=time.monotonic() + 0.1, clock=time.monotonic
        )
    assert any("set_config" in q for q in s.seen) and not any("typologies &&" in q for q in s.seen)
