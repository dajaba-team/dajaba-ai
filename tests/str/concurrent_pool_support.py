"""`test_concurrent_pool.py` 전용 fixture·helper (SCRUM-122).

운영 코드에 손대지 않고 LLM 호출을 "진입 대기" 로 바꾸는 `_LlmGate`, pool checkedout 측정 쓰레드,
전용 엔진 monkeypatch 를 모음. 테스트 파일은 흐름만 짧게.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure import llm_client as llm_client_mod
from aml_ai.shared.infrastructure.llm_client import LlmResult
from tests.str.integration_support import INTEGRATION_INTERNAL_KEY

POOL_SIZE = 2
POOL_TIMEOUT_S = 3
ENTER_WAIT_S = 5.0


@dataclass
class LlmGate:
    """가짜 LLM 호출의 진입·해제 — `entered >= POOL_SIZE` 되면 pool 이 꽉 찬 상태 보장."""

    entered: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    release: threading.Event = field(default_factory=threading.Event)


class _GatedLlm:
    def __init__(self, inner, gate: LlmGate) -> None:  # type: ignore[no-untyped-def]
        self._inner = inner
        self._gate = gate

    def complete_json(self, **kwargs) -> LlmResult:  # type: ignore[no-untyped-def]
        with self._gate.lock:
            self._gate.entered += 1
        if not self._gate.release.wait(timeout=30):
            raise RuntimeError("gate release timeout")
        return self._inner.complete_json(**kwargs)


@pytest.fixture
def short_timeout_engine(_pg_container, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """`pool_size=POOL_SIZE·max_overflow=0·pool_timeout=POOL_TIMEOUT_S` 전용 엔진."""
    from aml_ai.shared import db as db_mod

    url = _pg_container.get_connection_url()
    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=POOL_SIZE,
        max_overflow=0,
        pool_timeout=POOL_TIMEOUT_S,
        future=True,
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS ai"))
    db_mod.get_engine.cache_clear()
    monkeypatch.setattr(db_mod, "get_engine", lambda: engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def llm_gate(monkeypatch: pytest.MonkeyPatch) -> Iterator[LlmGate]:
    """draft_service·verify_service 의 `make_llm_client` 를 gate wrap 로 교체."""
    gate = LlmGate()
    original = llm_client_mod.make_llm_client

    def _wrapped(settings):  # type: ignore[no-untyped-def]
        return _GatedLlm(original(settings), gate)

    from aml_ai.str.application import draft_service as draft_mod
    from aml_ai.str.application import verify_service as verify_mod

    monkeypatch.setattr(draft_mod, "make_llm_client", _wrapped)
    monkeypatch.setattr(verify_mod, "make_llm_client", _wrapped)
    try:
        yield gate
    finally:
        gate.release.set()


@pytest.fixture
def concurrent_client(
    short_timeout_engine: Engine,
    _ops_seed,
    llm_gate: LlmGate,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("AI_LLM_MOCK", "true")
    monkeypatch.setenv("RAG_ENABLED", "false")
    monkeypatch.setenv("AI_INTERNAL_KEY", INTEGRATION_INTERNAL_KEY)
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v2")
    get_settings.cache_clear()
    with short_timeout_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.generations, ai.verification_runs RESTART IDENTITY"))
    from aml_ai.main import app

    with TestClient(app) as client:
        yield client


def watch_pool_max(pool, stop: threading.Event, record: dict[str, int]) -> None:
    while not stop.is_set():
        record["value"] = max(record["value"], pool.checkedout())
        time.sleep(0.05)


def wait_entered(gate: LlmGate, target: int) -> int:
    deadline = time.monotonic() + ENTER_WAIT_S
    while gate.entered < target and time.monotonic() < deadline:
        time.sleep(0.02)
    return gate.entered
