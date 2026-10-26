"""백엔드 → AI 내부 인증. 헤더 X-Internal-Key 가 .env AI_INTERNAL_KEY 와 같아야 한다. /v1/health 만 예외."""

from __future__ import annotations

import hmac

from fastapi import Depends, Header

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.errors import Unauthenticated

INTERNAL_KEY_HEADER = "X-Internal-Key"


def require_internal_key(
    x_internal_key: str | None = Header(default=None, alias=INTERNAL_KEY_HEADER),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.ai_internal_key:
        raise Unauthenticated("AI_INTERNAL_KEY is not configured")
    if not x_internal_key or not hmac.compare_digest(x_internal_key, settings.ai_internal_key):
        raise Unauthenticated("invalid internal key")
