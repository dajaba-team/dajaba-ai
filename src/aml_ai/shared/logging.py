"""JSON 한 줄 로그 + request_id.

남기지 않는 것: 계좌번호·금액·narrative/summary 본문·프롬프트 전문·조사역 메모·API 키·요청/응답 본문.
ID·건수·길이·시간·코드값만 (docs/shared/04).
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import override

from fastapi.exceptions import ValidationException
from pydantic import ValidationError
from pythonjsonlogger import jsonlogger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from aml_ai.shared.config import Settings

REQUEST_ID_HEADER = "X-Request-Id"
REQUEST_ID_MAX_LEN = 64  # verification_runs.request_id VARCHAR(64) (docs/shared/03, SCRUM-57·58)
LOG_SERVICE = "ai"
INTERNAL_ERROR_CODE = "INTERNAL"
INTERNAL_ERROR_MESSAGE = "internal error"
_request_id: ContextVar[str] = ContextVar("request_id", default="-")

logger = logging.getLogger(__name__)


def current_request_id() -> str:
    return _request_id.get()


def log_unhandled(exc: Exception) -> None:
    if isinstance(exc, (ValidationError, ValidationException)):
        errors = (
            exc.errors(include_input=False, include_url=False)
            if isinstance(exc, ValidationError)
            else exc.errors()
        )
        logger.error(
            "unhandled",
            extra={
                "error_type": type(exc).__name__,
                "errors": [{"loc": list(e["loc"]), "type": e["type"]} for e in errors],
            },
        )
    else:
        logger.exception("unhandled")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


class _JsonFormatter(jsonlogger.JsonFormatter):
    @override
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return (
            datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )


def setup_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
            rename_fields={"asctime": "ts", "levelname": "level", "name": "logger", "message": "msg"},
            static_fields={"service": LOG_SERVICE},
        )
    )
    handler.addFilter(_RequestIdFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level)
    logging.getLogger("uvicorn.access").disabled = True  # 접근 로그는 미들웨어가 한 줄로


class RequestIdMiddleware(BaseHTTPMiddleware):
    """백엔드 X-Request-Id 를 받아 쓰고, 없으면 만든다. 응답 헤더로 돌려준다.

    SCRUM-58 — 길이 ≤ `REQUEST_ID_MAX_LEN`(64) 아니면 새 ID 발급 + `request_id_replaced` 경고.
    verification_runs.request_id VARCHAR(64) commit 실패 방지(09 결정, docs/shared/03).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        raw = request.headers.get(REQUEST_ID_HEADER)
        if raw is not None and 1 <= len(raw) <= REQUEST_ID_MAX_LEN:
            rid = raw
        else:
            rid = uuid.uuid4().hex[:16]
            if raw is not None:  # 헤더가 왔는데 길이 범위 밖
                logger.warning("request_id_replaced", extra={"received_len": len(raw)})
        token = _request_id.set(rid)
        try:
            response = await call_next(request)
        except Exception as exc:
            log_unhandled(exc)
            response = JSONResponse(
                status_code=500,
                content={
                    "code": INTERNAL_ERROR_CODE,
                    "message": INTERNAL_ERROR_MESSAGE,
                    "request_id": current_request_id(),
                },
            )
        finally:
            _request_id.reset(token)
        response.headers[REQUEST_ID_HEADER] = rid
        return response
