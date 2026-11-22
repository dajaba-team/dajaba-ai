"""SCRUM-309 참고 사례 검색 전용 임베딩 — 전송·본문 읽기 전체를 한 마감으로 (추가 검토 1, docs/str/10 "참고 사례 검색").

공통 `HttpEmbeddingClient`(초안·적재 경로)는 그대로. 호출마다 비동기 클라이언트를 만들어 앱 수명 루프
(`reference_search_runtime`)에서 요청·본문 읽기 전체를 돌리고, 요청 스레드는 절대 마감까지만 기다림 — 넘으면 취소하고
502 `LLM_UNAVAILABLE`(검토 2). 응답 검사는 공통 클라이언트와 같음(응답 `model` = 요청 모델 · `index` 순서 · 차원).
실패 분류: HTTP 429 이고 본문이 `{"error": {"code": "insufficient_quota"}}` 일 때만 502 `LLM_BUDGET_EXCEEDED`, 나머지 502.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import TimeoutError as FutureTimeout

import httpx
from pydantic import ValidationError

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import BudgetExceeded, LlmUnavailable, RetrievalUnavailable
from aml_ai.shared.infrastructure.embedding_client import _EmbeddingResponse, _in_input_order  # noqa: PLC2701
from aml_ai.str.infrastructure import reference_search_runtime as runtime

_QUOTA = "insufficient_quota"


def is_quota(response: httpx.Response) -> bool:
    """429 본문의 최상위·`error` 가 객체이고 `error.code` 가 정확히 `insufficient_quota` 일 때만(추가 검토 1 M4)."""
    if response.status_code != httpx.codes.TOO_MANY_REQUESTS:
        return False
    try:
        body = json.loads(response.content)
    except ValueError:
        return False
    error = body.get("error") if isinstance(body, dict) else None
    return isinstance(error, dict) and error.get("code") == _QUOTA


def _left(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LlmUnavailable("embedding total timeout")
    return remaining


async def _post(
    settings: Settings, text: str, transport: httpx.AsyncBaseTransport | None, deadline: float
) -> httpx.Response:
    """루프 쪽 — 클라이언트 만들기 전·전송 직전에 마감 확인(루프가 밀려 만료된 요청은 전송 0, 검토 3)."""
    async with httpx.AsyncClient(transport=transport, timeout=_left(deadline)) as http:
        _left(deadline)
        return await http.post(
            f"{settings.llm_api_base.rstrip('/')}/embeddings",
            json={"model": settings.embedding_model.strip(), "input": [text]},
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        )


def embed_within(
    settings: Settings, text: str, deadline: float, *, transport: httpx.AsyncBaseTransport | None = None
) -> list[float]:
    """문장 하나 → 벡터. `deadline`(절대, 단조) 안에 응답 본문까지 다 받아야 — 앱 수명 루프에서 돌리고 요청 스레드는
    제출 뒤 남은 시간만 기다림. 만료면 future 취소 + 바로 502(검토 2 — DNS 등 남은 작업이 요청 스레드를 묶지 않음)."""
    model = settings.embedding_model.strip()
    if not model or not settings.llm_api_key:
        raise LlmUnavailable("embedding not configured")
    _left(deadline)
    future = runtime.submit(_post(settings, text, transport, deadline))
    try:
        response = future.result(timeout=max(0.0, deadline - time.monotonic()))
    except FutureTimeout:
        future.cancel()
        raise LlmUnavailable("embedding total timeout") from None
    except httpx.HTTPError as exc:
        raise LlmUnavailable("embedding unavailable") from exc
    if response.status_code != httpx.codes.OK:
        raise (BudgetExceeded if is_quota(response) else LlmUnavailable)("embedding unavailable")
    try:
        parsed = _EmbeddingResponse.model_validate_json(response.content)
        if (parsed.model or "").strip() != model or len(parsed.data) != 1:
            raise RetrievalUnavailable("embedding response mismatch")
        vec = _in_input_order(parsed.data)[0]
    except (ValidationError, RetrievalUnavailable) as exc:
        raise LlmUnavailable("embedding unavailable") from exc
    if len(vec) != settings.embedding_dim:
        raise LlmUnavailable("embedding unavailable")
    return vec
