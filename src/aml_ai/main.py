"""FastAPI 앱. 라우터 등록과 /v1/health 만 — 로직 없음.

기동 시: 설정 로드 → 로그 → 프롬프트 파일 해시 색인(prompt_versions) → 라우터 2개.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from aml_ai import __version__
from aml_ai.scoring.api.router import router as scoring_router
from aml_ai.shared.auth import require_internal_key
from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.db import ping as db_ping
from aml_ai.shared.errors import install_exception_handlers
from aml_ai.shared.infrastructure.tracing import shutdown_tracer
from aml_ai.shared.logging import RequestIdMiddleware, setup_logging
from aml_ai.shared.received_at import ReceivedAtMiddleware, ResponseDeadlineGuard
from aml_ai.shared.versioning import (
    health_versions,
    reference_search_problem,
    retrieval_version_problem,
    scoring_mode,
    str_index_problem,
)
from aml_ai.str.api.router import REFERENCE_SEARCH_PATH
from aml_ai.str.api.router import router as str_router
from aml_ai.str.infrastructure import reference_search_runtime as reference_runtime
from aml_ai.str.infrastructure import str_index_runtime
from aml_ai.str.infrastructure.chunk_context_check import verify_on_startup
from aml_ai.str.infrastructure.judge import judge_model_decision
from aml_ai.str.infrastructure.prompt_index import check_frozen_prompts, index_prompt_files
from aml_ai.str.infrastructure.retriever_rerank import rerank_response_model_problem, rerank_timeout_problem

log = logging.getLogger(__name__)


def _open_session():  # noqa: ANN202 — 기동 검사용 짧은 세션(엔진은 지연 생성)
    from sqlalchemy.orm import Session

    from aml_ai.shared.db import get_engine

    return Session(get_engine())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if not logging.getLogger().handlers:
        setup_logging(settings)
    if settings.rag_enabled and not settings.embedding_model:
        log.warning("embedding_model_missing")
    check_frozen_prompts()  # docs/str/05 동결 강제 — 파일 해시가 다르면 기동 실패
    # SCRUM-308-2 — 꼬리 붙인 버전 > 128자 · 켠 리랭커 한도 > 8초 · 허용 응답 모델 빈 값이면 요청 받기 전에 기동 실패
    problem = retrieval_version_problem(settings) or rerank_timeout_problem(settings)
    problem = problem or rerank_response_model_problem(settings) or reference_search_problem(settings)
    problem = problem or str_index_problem(settings)  # SCRUM-310
    if problem:
        raise RuntimeError(problem)
    verify_on_startup(settings, _open_session)  # SCRUM-308-3 — 켬+v4 만, 새 표 ≠ 지금 표면 기동 실패
    if settings.rag_enabled and settings.rag_reference_search_enabled:
        reference_runtime.start(settings)  # SCRUM-309 — manifest 버전 고정 · 검색 임베딩 루프
    if settings.rag_enabled and settings.str_index_enabled:
        str_index_runtime.start(settings)  # SCRUM-310 — 응답·새 행 버전 고정(검토 2)
    _, reason = judge_model_decision(settings)
    if reason is not None:
        log.warning(
            "judge_model_fallback",
            extra={
                "generate": settings.llm_model_generate,
                "judge": settings.llm_model_judge,
                "reason": reason,
            },
        )
    if settings.index_prompts_on_startup:
        index_prompt_files(settings)
    yield
    reference_runtime.stop()
    str_index_runtime.stop()
    shutdown_tracer()


app = FastAPI(
    title="dajaba AML AI",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
)
app.add_middleware(RequestIdMiddleware)
# SCRUM-309 검토 3 — 검색 입구에만, 응답 시작 직전 마감(요청 ID 헤더가 붙은 뒤라 RequestId 바깥)
app.add_middleware(ResponseDeadlineGuard, paths=(f"/v1{REFERENCE_SEARCH_PATH}",))
app.add_middleware(ReceivedAtMiddleware)  # 맨 바깥 — 요청이 들어온 시각(SCRUM-309)
install_exception_handlers(app)


@app.get("/v1/health", tags=["health"])
def health(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    """백엔드 AiHealthCheck 가 기동 시 한 번 부른다. 인증 없음."""
    return {
        "status": "ok",
        "db": db_ping(settings),
        "llm": "ok" if settings.llm_api_key or settings.ai_llm_mock else "missing_key",
        "scoring_mode": scoring_mode(settings),
        **health_versions(settings),
    }


app.include_router(scoring_router, prefix="/v1", dependencies=[Depends(require_internal_key)])
app.include_router(str_router, prefix="/v1", dependencies=[Depends(require_internal_key)])
