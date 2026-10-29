"""shared/infrastructure/openai_responses.parse_response 분기 — 가짜 HTTP 응답(MockTransport).

M1(상태 분류 우선) · H1(공급자 메시지 유출 금지) · 429 분리 · 408/5xx 처리 테스트 모음.
실제 호출은 @pytest.mark.live.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import BudgetExceeded, LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient

NARRATIVE_OK = json.dumps(
    {
        "narrative": [
            {"section": "SUMMARY", "text": "요약.", "cites": []},
            {"section": "WHO", "text": "누구.", "cites": []},
            {"section": "WHAT_WHEN_WHERE", "text": "언제.", "cites": []},
            {"section": "HOW", "text": "어떻게.", "cites": []},
            {"section": "WHY_SUSPICIOUS", "text": "왜.", "cites": []},
            {"section": "CONCLUSION", "text": "결론.", "cites": []},
        ]
    },
    ensure_ascii=False,
)


def _client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> HttpLlmClient:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL_GENERATE", "gpt-test")
    monkeypatch.setenv("LLM_API_BASE", "https://api.test.local/v1")
    get_settings.cache_clear()
    transport = httpx.MockTransport(handler)
    return HttpLlmClient(get_settings(), http=httpx.Client(transport=transport, timeout=5.0))


def _call(client: HttpLlmClient):
    return client.complete_json(
        system="sys", user="user", model="gpt-test", max_tokens=100, tag="narrative_v1"
    )


def _static(status: int, *, body: dict | None = None, text: str | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status, text=text)

    return handler


def test_parses_200(monkeypatch: pytest.MonkeyPatch) -> None:
    res = _call(
        _client(
            monkeypatch,
            _static(
                200,
                body={
                    "model": "gpt-test-2024",
                    "output_text": NARRATIVE_OK,
                    "usage": {"input_tokens": 100, "output_tokens": 50},
                },
            ),
        )
    )
    assert res.text == NARRATIVE_OK
    assert (res.model, res.tokens_in, res.tokens_out) == ("gpt-test-2024", 100, 50)


def test_output_array_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {
        "model": "gpt-test",
        "output": [{"content": [{"type": "output_text", "text": NARRATIVE_OK}]}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    assert _call(_client(monkeypatch, _static(200, body=body))).text == NARRATIVE_OK


def test_400_is_invalid_output_without_leaking_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """H1 — 공급자 message 가 외부 예외로 안 샘."""
    body = {"error": {"code": "invalid_json_schema", "message": "secret-value"}}
    with pytest.raises(LlmInvalidOutput) as exc:
        _call(_client(monkeypatch, _static(400, body=body)))
    assert "secret-value" not in str(exc.value)
    assert str(exc.value.message) == "llm invalid output"


def test_429_rate_limit_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 rate_limit → LlmUnavailable(재시도 1). SCRUM-15 10/29."""
    body = {"error": {"code": "rate_limit_exceeded", "message": "slow"}}
    with pytest.raises(LlmUnavailable):
        _call(_client(monkeypatch, _static(429, body=body)))


def test_429_insufficient_quota_is_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 insufficient_quota → BudgetExceeded(재시도 0, 일 한도)."""
    body = {"error": {"code": "insufficient_quota", "message": "daily"}}
    with pytest.raises(BudgetExceeded):
        _call(_client(monkeypatch, _static(429, body=body)))


def test_429_html_body_defaults_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """M1 — 상태 분류 우선. HTML/빈 body 429 는 code 없음 → LlmUnavailable."""
    with pytest.raises(LlmUnavailable):
        _call(_client(monkeypatch, _static(429, text="<html>Rate limit</html>")))


def test_408_is_unavailable_even_html(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(LlmUnavailable):
        _call(_client(monkeypatch, _static(408, text="timeout")))


def test_5xx_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"error": {"code": "server_error", "message": ""}}
    with pytest.raises(LlmUnavailable) as exc:
        _call(_client(monkeypatch, _static(503, body=body)))
    assert str(exc.value.message) == "llm unavailable"


def test_timeout_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timeout")

    with pytest.raises(LlmUnavailable):
        _call(_client(monkeypatch, handler))


def test_transport_error_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """M2 — ReadError·RemoteProtocolError 도 LlmUnavailable (httpx.TransportError 포괄)."""

    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("read error")

    with pytest.raises(LlmUnavailable):
        _call(_client(monkeypatch, handler))
