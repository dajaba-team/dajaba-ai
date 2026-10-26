"""LLM 클라이언트 1종. JSON 모드, 온도 0, 연결 실패·타임아웃만 1회 재시도 (스키마 실패 재생성은 호출자 몫).

녹화 모드(AI_LLM_MOCK=true): 호출 대신 tests/str/recorded/{prompt_version}/{sha256(messages)[:16]}.json 을 읽는다.
없으면 에러 — 조용히 지어내지 않는다 (docs/str/08).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.versioning import stable_json

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LlmResult:
    text: str  # JSON 문자열 그대로. 파싱·검증은 호출자(schemas)
    model: str  # API 가 돌려준 실제 모델 ID
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
        import hashlib

        key = hashlib.sha256(stable_json({"s": system, "u": user}).encode()).hexdigest()[:16]
        path = self._dir / tag / f"{key}.json"
        if not path.exists():
            raise LlmUnavailable(f"no recorded response: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        return LlmResult(
            text=data["text"], model=data.get("model", "recorded"), tokens_in=0, tokens_out=0, latency_ms=0
        )


class HttpLlmClient:
    """provider 별 HTTP 호출. W2 에 provider 1종만 구현한다 — 나머지 분기는 그때.

    TODO(W2): settings.llm_provider 에 따라 요청 본문·엔드포인트 분기. 응답에서 model·usage 추출.
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._http = httpx.Client(timeout=settings.llm_timeout_s)

    def complete_json(self, *, system: str, user: str, model: str, max_tokens: int, tag: str) -> LlmResult:
        started = time.perf_counter()
        for attempt in (1, 2):  # 연결 실패·타임아웃만 1회 재시도
            try:
                raw = self._call(system=system, user=user, model=model, max_tokens=max_tokens)
                break
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                if attempt == 2:
                    raise LlmUnavailable(f"llm unreachable: {type(exc).__name__}") from exc
                log.warning("llm_retry", extra={"tag": tag, "reason": type(exc).__name__})
        latency = int((time.perf_counter() - started) * 1000)
        return LlmResult(
            text=raw["text"],
            model=raw["model"],
            tokens_in=raw["tokens_in"],
            tokens_out=raw["tokens_out"],
            latency_ms=latency,
        )

    def _call(self, *, system: str, user: str, model: str, max_tokens: int) -> dict[str, object]:
        raise NotImplementedError("W2: provider 호출 구현 (docs/shared/05 LLM_PROVIDER)")


def make_llm_client(settings: Settings) -> LlmClient:
    if settings.ai_llm_mock:
        return RecordedLlmClient(settings.recorded_dir)
    return HttpLlmClient(settings)
