"""recording_key + HttpLlmClient 설정·결정성 테스트. HTTP 응답 파싱은 test_openai_responses.py."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient, recording_key

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
    return HttpLlmClient(
        get_settings(), http=httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)
    )


def _call(client: HttpLlmClient):
    return client.complete_json(
        system="sys", user="user", model="gpt-test", max_tokens=100, tag="narrative_v1"
    )


def _ok_handler():
    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "gpt-test",
                "output_text": NARRATIVE_OK,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    return h


def test_recording_key_differs_when_only_user_changes() -> None:
    assert recording_key("sys", "a") != recording_key("sys", "b")
    assert recording_key("sys", "a") == recording_key("sys", "a")


def test_recording_key_distinguishes_boundary() -> None:
    """단순 이어 붙이기면 ("sys", "user") 와 ("sysus", "er") 가 같은 키 — 우리는 아니어야 한다."""
    assert recording_key("sys", "user") != recording_key("sysus", "er")


def test_uses_reasoning_effort_when_temperature_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_TEMPERATURE_SUPPORTED=false → 호출 1회, body 에 reasoning.effort 만(폴백 없음)."""
    calls: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(json.loads(req.content))
        return _ok_handler()(req)

    _call(_client(monkeypatch, handler))
    assert len(calls) == 1
    assert "temperature" not in calls[0]
    assert calls[0].get("reasoning", {}).get("effort") == "low"


def test_uses_temperature_when_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM_TEMPERATURE_SUPPORTED=true → body 에 temperature=0, reasoning 없음."""
    calls: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(json.loads(req.content))
        return _ok_handler()(req)

    monkeypatch.setenv("LLM_TEMPERATURE_SUPPORTED", "true")
    _call(_client(monkeypatch, handler))
    assert calls[0]["temperature"] == 0.0
    assert "reasoning" not in calls[0]


def test_provider_unsupported_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_API_KEY", "x")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="구현되지 않음"):
        HttpLlmClient(get_settings())
