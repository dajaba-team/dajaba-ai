"""`summary_v1` 가 llm_output_model 매핑·json_schema·HttpLlmClient 경로에 다 걸리는지 (SCRUM-129).

녹화 1차 시도에서 `ValueError: unknown narrative prompt: summary_v1` 가 났던 자리 —
`shared/schemas/str/narrative_version.llm_output_model` 가 narrative·judge 만 알고 summary 를 몰랐음.
세 지점(매핑·스키마·실제 호출) 전부 녹색.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import HttpLlmClient
from aml_ai.shared.infrastructure.openai_responses import json_schema_for
from aml_ai.shared.schemas.str import SummaryOut, llm_output_model

SUMMARY_OK_TEXT = json.dumps(
    {
        "summary_lines": [
            "2026-11-06 보고 대상 계좌로 ACH 입금 3건이 들어옴.",
            "같은 날 입금 합계는 42,750.50 USD이며, 출금은 없음.",
        ],
        "model_focus": "모델은 account_in_counterparties_24h 신호를 가장 크게 봄",
    },
    ensure_ascii=False,
)


def test_llm_output_model_summary_v1_returns_summary_out() -> None:
    """★ 매핑 — `narrative_version._LLM_OUTPUT_MODELS` 에 summary_v1 등록."""
    assert llm_output_model("summary_v1") is SummaryOut


def test_json_schema_for_llm_output_model_summary_v1_has_fields() -> None:
    """★ Structured Output 스키마 — llm_output_model("summary_v1") 를 거친 뒤 summary_lines 1~6·80자·model_focus."""
    schema = json_schema_for(llm_output_model("summary_v1"), name="summary_v1")
    inner = schema.get("schema") or schema.get("json_schema", {}).get("schema") or schema
    assert "summary_lines" in inner.get("properties", {})
    assert "model_focus" in inner.get("properties", {})
    lines = inner["properties"]["summary_lines"]
    assert lines.get("minItems") == 1
    assert lines.get("maxItems") == 6
    assert lines["items"].get("maxLength") == 80


def test_summary_v1_schema_required_has_all_properties() -> None:
    """★ strict 모드 규칙 — 모든 property 가 required 에 있어야 OpenAI 가 받음 (2차 녹화 실패 재발 방지)."""
    schema = json_schema_for(llm_output_model("summary_v1"), name="summary_v1")
    inner = schema.get("schema") or schema.get("json_schema", {}).get("schema") or schema
    assert set(inner["required"]) == set(inner["properties"].keys())
    # model_focus 는 nullable 필수 — default 없음(스키마에 "default" 키가 남아 있으면 OpenAI 가 거부)
    assert "default" not in inner["properties"]["model_focus"]


def _client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> HttpLlmClient:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    monkeypatch.setenv("LLM_MODEL_GENERATE", "gpt-test")
    monkeypatch.setenv("LLM_API_BASE", "https://api.test.local/v1")
    get_settings.cache_clear()
    return HttpLlmClient(
        get_settings(), http=httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)
    )


def test_http_llm_client_summary_v1_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """★ 실제 경로 — HttpLlmClient.complete_json(tag="summary_v1") 가 SummaryOut 로 파싱됨.

    1차 녹화 시도에서 `complete_json → json_schema_for(llm_output_model("summary_v1"))` 가
    `ValueError: unknown narrative prompt: summary_v1` 던졌던 재현. 매핑 추가로 통과.
    """

    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "gpt-test",
                "output_text": SUMMARY_OK_TEXT,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = _client(monkeypatch, h)
    result = client.complete_json(
        system="sys", user="user", model="gpt-test", max_tokens=100, tag="summary_v1"
    )
    parsed = SummaryOut.model_validate_json(result.text)
    assert 1 <= len(parsed.summary_lines) <= 6
    assert parsed.model_focus is not None
