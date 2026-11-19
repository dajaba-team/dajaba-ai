"""SCRUM-322 LLM 호출 전체 마감 — 로컬 TCP 지연 서버 (docs/str/03 `/v1/cases/ask` 6단계, 08, 09 2026-11-19).

`total_timeout_s` 가 있으면 늦은 헤더 · 헤더 조각 · 본문 조각 어디서든 마감 시각 + 여유 안에 `LlmUnavailable` 로
돌아오고, 서버 쪽에서 본 연결도 그 여유 안에 닫히며, 작업 스레드가 남지 않는다. 정상·연결 실패·5xx 는 지금과
같은 결과·`llm_call` 로그. `total_timeout_s` 가 없으면(초안·검증·요약) 지금 경로 그대로 — 전체 마감 없음.
외부 네트워크·실제 LLM 0.
"""

from __future__ import annotations

import json
import logging
import threading
import time

import httpx
import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from tests.shared.llm_delay_server import DelayServer, closed_port_url

TOTAL_S = 0.3
SLACK_S = 0.15  # 290-1 테스트와 같은 여유 — 스레드 전환·연결 닫기
LATE_S = 1.5  # 늦은 헤더 — 마감보다 훨씬 뒤
STEP_S = 0.05  # 조각 간격 — 마감보다 짧아 작업별 timeout 으로는 안 끊김
OLD_WORKER = "llm-total-timeout"  # develop 의 작업 스레드 이름


def _client(monkeypatch: pytest.MonkeyPatch, base_url: str, **kw) -> HttpLlmClient:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_API_BASE", base_url)
    get_settings.cache_clear()
    return HttpLlmClient(get_settings(), **kw)


def _call(client: HttpLlmClient, **kw):
    return client.complete_json(
        system="s", user="u", model="gpt-test", max_tokens=10, tag="ask_plan_v1", **kw
    )


def _workers() -> list[str]:
    return [t.name for t in threading.enumerate() if t.name.startswith(OLD_WORKER) and t.is_alive()]


def _llm_call_logs(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == "llm_call"]


@pytest.mark.parametrize(
    ("mode", "delay"),
    [("late_header", LATE_S), ("header_chunks", STEP_S), ("body_chunks", STEP_S)],
)
def test_total_deadline_cuts_call_and_connection(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, mode: str, delay: float
) -> None:
    caplog.set_level(logging.INFO)
    server = DelayServer(mode, delay)
    client = _client(monkeypatch, server.base_url)
    started = time.monotonic()
    with pytest.raises(LlmUnavailable):
        _call(client, timeout_s=TOTAL_S, total_timeout_s=TOTAL_S)
    assert time.monotonic() - started < TOTAL_S + SLACK_S  # 호출자는 마감에 돌아옴
    time.sleep(SLACK_S)
    assert (
        server.closed_at is not None and server.closed_at < TOTAL_S + 2 * SLACK_S
    )  # 연결도 마감 근처에 닫힘
    assert _workers() == []  # 마감 뒤 남는 작업 스레드 없음
    assert not server.sent_all and _llm_call_logs(caplog) == []  # 마감 뒤 응답은 쓰지 않음
    server.join()


@pytest.mark.parametrize("total", [None, 1.0])
def test_fast_response_same_result_and_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, total: float | None
) -> None:
    caplog.set_level(logging.INFO)
    server = DelayServer("ok")
    res = _call(_client(monkeypatch, server.base_url), timeout_s=1.0, total_timeout_s=total)
    assert json.loads(res.text)["kind"] == "OUT_OF_SCOPE" and res.model == "gpt-test"
    assert [r.status for r in _llm_call_logs(caplog)] == [200]
    server.join()


@pytest.mark.parametrize("total", [None, 1.0])
def test_connection_failure_same_error_no_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, total: float | None
) -> None:
    caplog.set_level(logging.INFO)
    client = _client(monkeypatch, closed_port_url())
    with pytest.raises(LlmUnavailable, match="^llm unavailable$"):
        _call(client, timeout_s=1.0, total_timeout_s=total)
    assert _llm_call_logs(caplog) == []


@pytest.mark.parametrize("total", [None, 1.0])
def test_5xx_same_error_and_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, total: float | None
) -> None:
    caplog.set_level(logging.INFO)
    server = DelayServer("status_500")
    with pytest.raises(LlmUnavailable):
        _call(_client(monkeypatch, server.base_url), timeout_s=1.0, total_timeout_s=total)
    assert [r.status for r in _llm_call_logs(caplog)] == [500]
    server.join()


def test_without_total_keeps_current_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """초안·검증·요약 — 주입한 동기 클라이언트로 한 번, 작업별 timeout 만이라 조각 응답은 끝까지 받음(지금과 같음)."""
    server = DelayServer("header_chunks", 0.01)
    sent: list[httpx.Request] = []
    http = httpx.Client(event_hooks={"request": [sent.append]})
    res = _call(_client(monkeypatch, server.base_url, http=http), timeout_s=TOTAL_S)
    assert json.loads(res.text)["kind"] == "OUT_OF_SCOPE"
    assert len(sent) == 1
    server.join()
