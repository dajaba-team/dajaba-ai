"""JSON 한 줄 로그 + request_id.

찍지 않는 것: 계좌번호·금액·narrative/summary 본문·프롬프트 전문·API 키. ID·건수·길이·시간만 (docs/shared/04).
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

from pythonjsonlogger import jsonlogger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from aml_ai.shared.config import Settings

REQUEST_ID_HEADER = "X-Request-Id"
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id() -> str:
    return _request_id.get()


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


def setup_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s")
    )
    handler.addFilter(_RequestIdFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level)
    logging.getLogger("uvicorn.access").disabled = True  # 접근 로그는 미들웨어가 한 줄로


class RequestIdMiddleware(BaseHTTPMiddleware):
    """백엔드 X-Request-Id 를 받아 쓰고, 없으면 만든다. 응답 헤더로 돌려준다."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
        token = _request_id.set(rid)
        try:
            response = await call_next(request)
        finally:
            _request_id.reset(token)
        response.headers[REQUEST_ID_HEADER] = rid
        return response
