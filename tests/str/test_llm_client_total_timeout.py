"""HttpLlmClient `total_timeout_s` — 호출 전체 제한 (SCRUM-290 추가 검토 1, docs/str/03 `/v1/cases/ask` 6단계).

httpx timeout 은 읽기마다 다시 걸린다. 응답 조각이 제한보다 짧은 간격으로 계속 오면 호출 전체는 늘어난다.
설계 문서 "읽기마다 9초, 제한 10초" 를 같은 비율의 짧은 시간(읽기 0.18초, 제한 0.2초)으로 재현.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient

READ_DELAY_S = 0.18  # 9초 / 50
TOTAL_S = 0.2  # 10초 / 50
SLACK_S = 0.15  # 스레드 전환·닫기 여유
BODY = json.dumps(
    {
        "model": "gpt-test",
        "output_text": json.dumps({"kind": "OUT_OF_SCOPE", "out_of_scope_reason": "JUDGMENT", "bundles": []}),
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
).encode()


class _SlowStream(httpx.SyncByteStream):
    def __init__(self, delay_s: float, parts: int = 4) -> None:
        self._delay, self._parts = delay_s, parts

    def __iter__(self):
        step = len(BODY) // self._parts + 1
        for i in range(0, len(BODY), step):
            time.sleep(self._delay)
            yield BODY[i : i + step]


def _client(monkeypatch: pytest.MonkeyPatch, delay_s: float, calls: list[Any]) -> HttpLlmClient:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_API_BASE", "https://api.test.local/v1")
    get_settings.cache_clear()

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, stream=_SlowStream(delay_s))

    http = httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)
    return HttpLlmClient(get_settings(), http=http)


def _call(client: HttpLlmClient, **kw):
    return client.complete_json(
        system="sys", user="user", model="gpt-test", max_tokens=100, tag="ask_plan_v1", **kw
    )


def test_slow_chunked_response_is_cut_at_total_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    client = _client(monkeypatch, READ_DELAY_S, calls)
    started = time.monotonic()
    with pytest.raises(LlmUnavailable):
        _call(client, timeout_s=TOTAL_S, total_timeout_s=TOTAL_S)
    assert time.monotonic() - started < TOTAL_S + SLACK_S
    assert len(calls) == 1  # 재시도 0


def test_fast_response_within_total_limit_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []
    res = _call(_client(monkeypatch, 0.0, calls), timeout_s=1.0, total_timeout_s=1.0)
    assert json.loads(res.text)["kind"] == "OUT_OF_SCOPE"
    assert len(calls) == 1


def test_without_total_limit_behaviour_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """초안·검증·요약처럼 total_timeout_s 를 안 넘기면 기존 그대로 끝까지 읽는다."""
    calls: list[Any] = []
    res = _call(_client(monkeypatch, 0.02, calls))
    assert json.loads(res.text)["kind"] == "OUT_OF_SCOPE"
