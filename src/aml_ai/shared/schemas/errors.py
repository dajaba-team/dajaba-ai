"""규약 6절 에러 JSON. 실제 생성은 shared/errors.py 가 한다 — 여기는 계약 테스트용 모양."""

from __future__ import annotations

from aml_ai.shared.schemas.common import StrictModel


class ErrorBody(StrictModel):
    code: str
    message: str
    request_id: str
