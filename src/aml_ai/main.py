"""FastAPI 앱. 라우터 등록과 /v1/health 만 — 로직 없음.

기동 시: 설정 로드 → 로그 → 프롬프트 파일 해시 색인(prompt_versions) → 라우터 2개.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from aml_ai import __version__
from aml_ai.scoring.api.router import router as scoring_router
from aml_ai.shared.auth import require_internal_key
from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.db import ping as db_ping
from aml_ai.shared.errors import install_exception_handlers
from aml_ai.shared.logging import RequestIdMiddleware, setup_logging
from aml_ai.shared.versioning import health_versions
from aml_ai.str.api.router import router as str_router
from aml_ai.str.infrastructure.prompt_index import check_frozen_prompts, index_prompt_files


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings)
    check_frozen_prompts()  # docs/str/05 동결 강제 — 파일 해시가 다르면 기동 실패
    if settings.index_prompts_on_startup:
        index_prompt_files(settings)
    yield


app = FastAPI(
    title="dajaba AML AI",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
)
app.add_middleware(RequestIdMiddleware)
install_exception_handlers(app)


@app.get("/v1/health", tags=["health"])
def health(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """백엔드 AiHealthCheck 가 기동 시 한 번 부른다. 인증 없음."""
    return {
        "status": "ok",
        "db": db_ping(settings),
        "llm": "ok" if settings.llm_api_key or settings.ai_llm_mock else "missing_key",
        **health_versions(settings),
    }


app.include_router(scoring_router, prefix="/v1", dependencies=[Depends(require_internal_key)])
app.include_router(str_router, prefix="/v1", dependencies=[Depends(require_internal_key)])
