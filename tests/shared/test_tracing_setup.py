"""SCRUM-274 — 추적 켜기·끄기·싱글턴·감싸기·종료 (docs/shared/04 "추적", shared/05 변수).

끔(기본) → 아무것도 안 함 · 켰는데 키 없음/초기화 실패 → 경고 1줄(키 값 없이) + 끔 · 클라이언트 프로세스당 하나 ·
녹화 재생은 안 감쌈 · 전용 TracerProvider(전역 OTel 그대로, ★A 덧붙임 1) · 종료 flush 는 제한 시간까지만.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace as otel_trace

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.infrastructure import tracing
from aml_ai.shared.infrastructure.embedding_client import HttpEmbeddingClient, make_embedding_client
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient, RecordedLlmClient, make_llm_client
from aml_ai.shared.infrastructure.tracing import TracedEmbeddingClient, TracedLlmClient
from tests.shared.tracing_support import (
    PUBLIC_KEY,
    SECRET_KEY,
    FakeTracer,
    _reset_tracing,  # noqa: F401 — autouse
    enable_tracing,
    tracing_records,
)


@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """리포 루트 `.env` 를 읽지 않는다 — 로컬 `.env` 의 `LANGFUSE_*` 값이 기본값 검사를 흔들지 않게.

    `get_settings()` 가 앱 안쪽에서 불려도 같은 설정을 쓰도록 `Settings.model_config` 를 바꾼다.
    환경 변수(`monkeypatch.setenv`)는 그대로 읽힌다.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()  # 이 파일의 설정이 다음 테스트로 새지 않게


def _real_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_LLM_MOCK", "false")
    monkeypatch.setenv("LLM_API_KEY", "sk-llm-test")
    get_settings.cache_clear()


# ───────── 끔 ─────────


def test_disabled_by_default_does_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
    _real_llm(monkeypatch)
    built: list[object] = []
    monkeypatch.setattr(tracing, "Langfuse", lambda **kw: built.append(kw))
    settings = get_settings()
    assert settings.langfuse_enabled is False
    assert settings.langfuse_base_url == "http://langfuse-web:3000"
    with caplog.at_level(logging.DEBUG):
        assert tracing.get_tracer(settings) is None
        assert type(make_llm_client(settings)) is HttpLlmClient
        assert type(make_embedding_client(settings)) is HttpEmbeddingClient
    assert built == []
    assert [r for r in caplog.records if r.name == tracing.__name__] == []


def test_disabled_ignores_injected_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    """`LANGFUSE_ENABLED=false` 면 넣어 둔 tracer 가 있어도 감싸지 않는다."""
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    _real_llm(monkeypatch)
    tracing.set_tracer(FakeTracer())
    assert type(make_llm_client(get_settings())) is HttpLlmClient


# ───────── 켰는데 키 없음 · 초기화 실패 ─────────


def test_enabled_without_keys_warns_once_and_disables(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    enable_tracing(monkeypatch, keys=False)
    _real_llm(monkeypatch)
    settings = get_settings()
    built: list[object] = []
    monkeypatch.setattr(tracing, "Langfuse", lambda **kw: built.append(kw))
    with caplog.at_level(logging.WARNING):
        assert tracing.get_tracer(settings) is None
        assert tracing.get_tracer(settings) is None
        client = make_llm_client(settings)
    assert type(client) is HttpLlmClient  # 기동·호출 정상
    assert built == []
    records = tracing_records(caplog, "langfuse_disabled")
    assert len(records) == 1
    assert records[0].reason == "missing_key"


def test_init_failure_warns_and_disables(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = enable_tracing(monkeypatch)

    def boom(**kw: object) -> None:
        raise ValueError(f"bad init {kw.get('secret_key')}")

    monkeypatch.setattr(tracing, "Langfuse", boom)
    with caplog.at_level(logging.WARNING):
        assert tracing.get_tracer(settings) is None
    records = tracing_records(caplog, "langfuse_disabled")
    assert len(records) == 1
    assert records[0].reason == "init_failed"
    assert PUBLIC_KEY not in caplog.text and SECRET_KEY not in caplog.text


# ───────── 싱글턴 · 감싸기 ─────────


def test_client_is_built_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = enable_tracing(monkeypatch)
    built: list[dict] = []

    def fake_langfuse(**kw: object) -> FakeTracer:
        built.append(kw)
        return FakeTracer()

    monkeypatch.setattr(tracing, "Langfuse", fake_langfuse)
    first = tracing.get_tracer(settings)
    assert first is not None and tracing.get_tracer(settings) is first
    assert len(built) == 1
    kw = built[0]
    assert kw["public_key"] == PUBLIC_KEY and kw["secret_key"] == SECRET_KEY
    assert kw["base_url"] == "http://127.0.0.1:9"
    assert kw["timeout"] == tracing.LANGFUSE_HTTP_TIMEOUT_S
    assert kw["tracer_provider"] is not None  # 전용 provider (★A ④-3)


def test_make_clients_wrap_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    enable_tracing(monkeypatch)
    _real_llm(monkeypatch)
    tracing.set_tracer(FakeTracer())
    settings = get_settings()
    assert isinstance(make_llm_client(settings), TracedLlmClient)
    assert isinstance(make_embedding_client(settings), TracedEmbeddingClient)


def test_recorded_client_is_not_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    enable_tracing(monkeypatch)  # conftest: AI_LLM_MOCK=true
    tracing.set_tracer(FakeTracer())
    assert type(make_llm_client(get_settings())) is RecordedLlmClient


def test_real_langfuse_keeps_global_tracer_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """★A 덧붙임 1 — 실제 SDK 를 만들어도 전역 TracerProvider 는 원래 값 그대로."""
    settings = enable_tracing(monkeypatch)
    before = otel_trace.get_tracer_provider()
    lf = tracing.get_tracer(settings)
    try:
        assert lf is not None
        assert otel_trace.get_tracer_provider() is before
    finally:
        tracing.shutdown_tracer(timeout_s=1.0)


# ───────── 종료 ─────────


def test_shutdown_waits_only_until_timeout() -> None:
    release = threading.Event()
    tracer = FakeTracer(shutdown_wait=release)
    tracing.set_tracer(tracer)
    started = time.monotonic()
    try:
        tracing.shutdown_tracer(timeout_s=0.2)
        elapsed = time.monotonic() - started
    finally:
        release.set()
    assert tracer.shutdown_calls == 1
    assert elapsed < 1.0


def test_shutdown_without_tracer_is_noop() -> None:
    tracing.shutdown_tracer(timeout_s=0.1)


def test_lifespan_shuts_tracer_down_on_exit() -> None:
    tracer = FakeTracer()
    tracing.set_tracer(tracer)
    from aml_ai.main import app

    with TestClient(app) as c:
        assert c.get("/v1/health").status_code == 200
        assert tracer.shutdown_calls == 0  # 요청 경로에서 flush·shutdown 없음
    assert tracer.shutdown_calls == 1
