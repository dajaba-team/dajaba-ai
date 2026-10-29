"""LLM 클라이언트 1종 — OpenAI Responses API, 녹화 재생.

- `recording_key(system, user)` — 녹화·재생이 쓰는 유일한 키 함수(docs/str/08).
- `RecordedLlmClient`: `AI_LLM_MOCK=true` 때. `recorded/{tag}/{key}.json` 없으면 LlmUnavailable.
- `HttpLlmClient`: provider 1종(`openai`). Responses API + `text.format=json_schema` 로 NarrativeOut
  강제. 결정성은 `LLM_TEMPERATURE_SUPPORTED` + `LLM_REASONING_EFFORT` 설정으로 고정 — 호출마다 폴백 없음
  (docs/str/09 10/29 SCRUM-15). 연결 재시도 없음 — 재시도는 백엔드 AiClient 1회(str/03).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.infrastructure.openai_responses import (
    build_body,
    extract_output_text,
    json_schema_for,
    parse_response,
)
from aml_ai.shared.versioning import stable_json

log = logging.getLogger(__name__)


def recording_key(system: str, user: str) -> str:
    """녹화 파일 이름의 16자. `stable_json({"s","u"})` 로 경계 명시(단순 이어 붙이기는 모호)."""
    return hashlib.sha256(stable_json({"s": system, "u": user}).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class LlmResult:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


class LlmClient(Protocol):
    def complete_json(
        self, *, system: str, user: str, model: str, max_tokens: int, tag: str
    ) -> LlmResult: ...


class RecordedLlmClient:
    """녹화 재생. tag = prompt_version."""

    def __init__(self, recorded_dir: Path) -> None:
        self._dir = recorded_dir

    def complete_json(self, *, system: str, user: str, model: str, max_tokens: int, tag: str) -> LlmResult:
        key = recording_key(system, user)
        path = self._dir / tag / f"{key}.json"
        if not path.exists():
            raise LlmUnavailable(f"no recorded response: {tag}/{key}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return LlmResult(
            text=data["text"],
            model=data.get("model", "recorded"),
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
        )


class HttpLlmClient:
    """OpenAI Responses API + Structured Output(json_schema). provider 1종(docs/str/07·09)."""

    def __init__(self, settings: Settings, http: httpx.Client | None = None) -> None:
        if settings.llm_provider != "openai":
            raise RuntimeError(
                f"LLM_PROVIDER='{settings.llm_provider}' 는 구현되지 않음 — 지금은 'openai' 만"
            )
        if not settings.llm_api_key:
            raise RuntimeError("LLM_API_KEY 가 비어 있음 — docs/shared/05")
        self._s = settings
        self._http = http or httpx.Client(timeout=settings.llm_timeout_s)

    def complete_json(self, *, system: str, user: str, model: str, max_tokens: int, tag: str) -> LlmResult:
        from aml_ai.shared.schemas.str import NarrativeOut

        schema = json_schema_for(NarrativeOut, name=tag)
        body = build_body(
            system,
            user,
            model,
            max_tokens,
            schema,
            temperature_supported=self._s.llm_temperature_supported,
            reasoning_effort=self._s.llm_reasoning_effort,
        )
        started = time.perf_counter()
        raw = self._post(body, tag=tag)
        latency = int((time.perf_counter() - started) * 1000)
        text = extract_output_text(raw)
        usage = raw.get("usage") or {}
        return LlmResult(
            text=text,
            model=str(raw.get("model", model) or model),
            tokens_in=int(usage.get("input_tokens", 0) or 0),
            tokens_out=int(usage.get("output_tokens", 0) or 0),
            latency_ms=latency,
        )

    def _post(self, body: dict, *, tag: str) -> dict:
        headers = {
            "Authorization": f"Bearer {self._s.llm_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._s.llm_api_base.rstrip('/')}/responses"
        try:
            resp = self._http.post(url, json=body, headers=headers)
        except httpx.TransportError as exc:
            # TransportError 는 TimeoutException·ConnectError·ReadError·RemoteProtocolError 포괄
            # (SCRUM-15 adversarial M2). 백엔드가 1회 재시도하는 LLM_UNAVAILABLE 로 통일.
            raise LlmUnavailable("llm unavailable") from exc
        log.info(
            "llm_call",
            extra={"status": resp.status_code, "model": body.get("model"), "tag": tag},
        )
        return parse_response(resp)


def make_llm_client(settings: Settings) -> LlmClient:
    if settings.ai_llm_mock:
        return RecordedLlmClient(settings.recorded_dir)
    return HttpLlmClient(settings)
