"""예외 한 벌 + HTTP 매핑. 라우터에서 HTTPException 을 직접 만들지 않는다 (docs/str/03 에러 표).

응답 형식 (규약 6절): {"code": "...", "message": "...", "request_id": "..."}
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from aml_ai.shared.logging import current_request_id

log = logging.getLogger(__name__)


class AiError(Exception):
    """모든 업무 예외의 부모. code 는 규약 6절 에러 코드, status 는 HTTP."""

    status: int = 500
    code: str = "INTERNAL"

    def __init__(self, message: str = "", **detail: object) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.detail = detail


class InvalidRequest(AiError):
    status, code = 400, "INVALID_REQUEST"


class Unauthenticated(AiError):
    status, code = 401, "UNAUTHENTICATED"


class DraftNotFound(AiError):
    status, code = 404, "DRAFT_NOT_FOUND"


class LlmInvalidOutput(AiError):
    """스키마 검증 실패 — 1회 재생성 뒤에도 실패했을 때. 백엔드 재시도 0회."""

    status, code = 502, "LLM_INVALID_OUTPUT"


class LlmUnavailable(AiError):
    """연결 실패·타임아웃. 백엔드 AiClient 가 1회 재시도하는 유일한 코드 (안건 21)."""

    status, code = 502, "LLM_UNAVAILABLE"


class BudgetExceeded(AiError):
    status, code = 502, "LLM_BUDGET_EXCEEDED"


class RetrievalUnavailable(AiError):
    """검색 실패. 호출자(draft_service)는 이걸 잡아 references=[] 로 진행한다 — 밖으로 나가지 않는다."""

    status, code = 502, "RETRIEVAL_UNAVAILABLE"


def _body(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message, "request_id": current_request_id()}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AiError)
    async def _ai_error(_: Request, exc: AiError) -> JSONResponse:
        log.warning("ai_error", extra={"error_code": exc.code, **exc.detail})
        return JSONResponse(status_code=exc.status, content=_body(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 어느 필드가 틀렸는지는 message 에 — 백엔드가 로그로 볼 수 있게. 값은 넣지 않는다.
        fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors()[:5])
        return JSONResponse(status_code=400, content=_body("INVALID_REQUEST", f"invalid fields: {fields}"))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled")
        return JSONResponse(status_code=500, content=_body("INTERNAL", "internal error"))
