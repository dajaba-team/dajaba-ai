"""요청이 들어온 시각(단조 시계) · 응답 시작 직전 마감 확인 (SCRUM-309 추가 검토 2·3).

- `ReceivedAtMiddleware` — 라우터 의존성·작업 스레드 대기보다 먼저 들어온 시각을 기록(`request.state.received_at`).
- `ResponseDeadlineGuard` — 정해 준 경로에만. 라우터가 `request.state.response_deadline` 에 적어 둔 절대 마감이
  `http.response.start` 를 보내기 직전에 지났으면 200 을 규약 502 `LLM_UNAVAILABLE` 본문으로 바꿈(성공 로그·응답 검증 대기
  포함). 마감이 없거나 200 이 아니면 그대로.
둘 다 순수 ASGI 라 요청 본문에 손대지 않는다.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from aml_ai.shared.errors import LlmUnavailable
from aml_ai.shared.logging import REQUEST_ID_HEADER

RECEIVED_AT = "received_at"
RESPONSE_DEADLINE = "response_deadline"
_OK = 200
_EXPIRED = "response deadline exceeded"

log = logging.getLogger(__name__)


class ReceivedAtMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})[RECEIVED_AT] = time.monotonic()
        await self.app(scope, receive, send)


def _expired_502(start: dict) -> tuple[dict, dict]:
    rid_key = REQUEST_ID_HEADER.lower().encode()
    rid = next((v for k, v in start.get("headers", []) if k.lower() == rid_key), b"")
    body = json.dumps({"code": LlmUnavailable.code, "message": _EXPIRED, "request_id": rid.decode()}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if rid:
        headers.append((rid_key, rid))
    return {"type": "http.response.start", "status": LlmUnavailable.status, "headers": headers}, {
        "type": "http.response.body",
        "body": body,
    }


class ResponseDeadlineGuard:
    def __init__(self, app: Any, *, paths: tuple[str, ...]) -> None:
        self.app, self.paths = app, paths

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") not in self.paths:
            await self.app(scope, receive, send)
            return
        replaced = False

        async def guarded(message: dict) -> None:
            nonlocal replaced
            if replaced:
                return  # 바꾼 뒤 원래 본문은 버림
            deadline = scope.get("state", {}).get(RESPONSE_DEADLINE)
            if (
                message["type"] == "http.response.start"
                and message.get("status") == _OK
                and deadline is not None
                and time.monotonic() >= deadline
            ):
                replaced = True
                log.warning("response_deadline_exceeded", extra={"reason": "budget"})
                for m in _expired_502(message):
                    await send(m)
                return
            await send(message)

        await self.app(scope, receive, guarded)
