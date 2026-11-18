"""SCRUM-274 — 추적 테스트 공용 가짜 tracer (docs/shared/04 "추적"). SDK 실제 전송 없음.

`FakeTracer` 는 `Langfuse.start_observation`·`shutdown` 의 부분집합만 흉내 낸다 — 받은 kwargs 를 그대로 쌓아
테스트가 name·model·usage·trace_context·metadata 를 비교한다.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pytest

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.infrastructure import tracing
from aml_ai.shared.infrastructure.llm_client import LlmResult
from aml_ai.shared.logging import _request_id

PUBLIC_KEY = "pk-lf-test-public-0001"
SECRET_KEY = "sk-lf-test-secret-0002"


@dataclass
class FakeObservation:
    start: dict[str, Any]
    updates: list[dict[str, Any]] = field(default_factory=list)
    ended: int = 0
    raise_on_update: Exception | None = None
    raise_on_end: Exception | None = None

    def update(self, **kwargs: Any) -> FakeObservation:
        if self.raise_on_update is not None:
            raise self.raise_on_update
        self.updates.append(kwargs)
        return self

    def end(self, **kwargs: Any) -> FakeObservation:
        if self.raise_on_end is not None:
            raise self.raise_on_end
        self.ended += 1
        return self

    def merged(self) -> dict[str, Any]:
        """시작 kwargs + update 들을 차례로 덮은 최종 모양."""
        out = dict(self.start)
        for u in self.updates:
            out.update(u)
        return out


class FakeTracer:
    def __init__(
        self,
        *,
        raise_on_start: Exception | None = None,
        raise_on_update: Exception | None = None,
        raise_on_end: Exception | None = None,
        shutdown_wait: threading.Event | None = None,
    ) -> None:
        self.observations: list[FakeObservation] = []
        self.shutdown_calls = 0
        self._lock = threading.Lock()
        self._raise_on_start = raise_on_start
        self._raise_on_update = raise_on_update
        self._raise_on_end = raise_on_end
        self._shutdown_wait = shutdown_wait

    def start_observation(self, **kwargs: Any) -> FakeObservation:
        if self._raise_on_start is not None:
            raise self._raise_on_start
        obs = FakeObservation(
            start=kwargs, raise_on_update=self._raise_on_update, raise_on_end=self._raise_on_end
        )
        with self._lock:
            self.observations.append(obs)
        return obs

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        if self._shutdown_wait is not None:
            self._shutdown_wait.wait()


class StubLlm:
    """고정 결과 또는 예외. 호출 kwargs 기록."""

    def __init__(self, *, result: LlmResult | None = None, exc: Exception | None = None) -> None:
        self.result = result or LlmResult(
            text='{"ok": true}', model="stub-model-returned", tokens_in=120, tokens_out=45, latency_ms=7
        )
        self.exc = exc
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, **kwargs: Any) -> LlmResult:
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return self.result


class StubEmbedding:
    model = "stub-embedding-model"

    def __init__(self, *, exc: Exception | None = None) -> None:
        self.exc = exc

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.exc is not None:
            raise self.exc
        return [[0.125, 0.25, 0.5] for _ in texts]


def enable_tracing(monkeypatch: pytest.MonkeyPatch, *, keys: bool = True) -> Settings:
    """`LANGFUSE_ENABLED=true` (+ 키) 로 설정을 다시 읽는다."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:9")  # 닿지 않는 주소 — 실제 전송 없음
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", PUBLIC_KEY if keys else "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", SECRET_KEY if keys else "")
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture(autouse=True)
def _reset_tracing() -> Iterator[None]:
    """테스트마다 싱글턴·한 번만 경고 기록을 비운다."""
    tracing.reset_tracing()
    yield
    tracing.reset_tracing()


@contextmanager
def request_id(value: str) -> Iterator[None]:
    token = _request_id.set(value)
    try:
        yield
    finally:
        _request_id.reset(token)


def tracing_records(caplog: pytest.LogCaptureFixture, msg: str) -> list[Any]:
    return [r for r in caplog.records if r.name == tracing.__name__ and r.getMessage() == msg]
