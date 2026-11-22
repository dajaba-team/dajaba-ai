"""STR 라우터. 백엔드 Controller 와 같은 역할 — 검증·호출·응답만."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.db import get_session
from aml_ai.shared.errors import InvalidRequest
from aml_ai.shared.received_at import RECEIVED_AT, RESPONSE_DEADLINE
from aml_ai.shared.schemas.str import (
    AskRequest,
    AskResponse,
    DraftRequest,
    DraftResponse,
    ReferenceSearchRequest,
    ReferenceSearchResponse,
    StrIndexRequest,
    StrIndexResponse,
    SummaryRequest,
    SummaryResponse,
    VerifyRequest,
    VerifyResponse,
)
from aml_ai.str.application.ask_service import AskService
from aml_ai.str.application.draft_service import DraftService
from aml_ai.str.application.reference_search_service import ReferenceSearchService, search_deadline
from aml_ai.str.application.str_index_service import StrIndexService
from aml_ai.str.application.summary_service import SummaryService
from aml_ai.str.application.verify_service import VerifyService

router = APIRouter(tags=["str"])


def _draft_service(
    session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> DraftService:
    return DraftService.build(session, settings)


def _verify_service(
    session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> VerifyService:
    return VerifyService.build(session, settings)


def _summary_service(
    session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> SummaryService:
    return SummaryService.build(session, settings)


def _ask_service(
    session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> AskService:
    return AskService.build(session, settings)


@router.post("/str/drafts", response_model=DraftResponse, summary="STR 초안 생성 (규약 5.1)")
def create_draft(req: DraftRequest, svc: DraftService = Depends(_draft_service)) -> DraftResponse:
    return svc.create(req)


@router.post(
    "/str/verify", response_model=VerifyResponse, summary="초안 검증 — 코드 4종 + 평가자 5종 (규약 5.3)"
)
def verify_draft(req: VerifyRequest, svc: VerifyService = Depends(_verify_service)) -> VerifyResponse:
    return svc.verify(req)


@router.post("/cases/summary", response_model=SummaryResponse, summary="케이스 요약 5줄 (W4 말)")
def summarize_case(req: SummaryRequest, svc: SummaryService = Depends(_summary_service)) -> SummaryResponse:
    return svc.summarize(req)


@router.post("/cases/ask", response_model=AskResponse, summary="케이스 질문 답변 (규약 5.4)")
def ask_case(req: AskRequest, svc: AskService = Depends(_ask_service)) -> AskResponse:
    """동기 def — 호출 전체 마감 경로를 이벤트 루프 스레드에서 부르지 않는다(docs/str/03, SCRUM-322)."""
    return svc.ask(req)


def _reference_search_enabled(settings: Settings = Depends(get_settings)) -> None:
    """SCRUM-309 — 스위치·RAG 가 꺼져 있으면 400(설계 13-4). 요청 본문 검사보다 먼저(의존성 먼저 풀림) · DB·임베딩 0."""
    if not (settings.rag_enabled and settings.rag_reference_search_enabled):
        raise InvalidRequest("reference search disabled")


def _budget_ms(x_budget_ms: str | None = Header(default=None, alias="X-Budget-Ms")) -> int | None:
    if x_budget_ms is None:
        return None
    if not x_budget_ms.isdigit() or int(x_budget_ms) <= 0:
        raise InvalidRequest("invalid X-Budget-Ms")
    return int(x_budget_ms)


def _reference_search_service(
    session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> ReferenceSearchService:
    return ReferenceSearchService.build(session, settings)


REFERENCE_SEARCH_PATH = "/references/search"


@router.post(
    REFERENCE_SEARCH_PATH,
    response_model=ReferenceSearchResponse,
    summary="참고 사례 검색 (설계 문서 5.1, SCRUM-309)",
    dependencies=[Depends(_reference_search_enabled)],
)
def search_references(
    req: ReferenceSearchRequest,
    request: Request,
    budget_ms: int | None = Depends(_budget_ms),
    svc: ReferenceSearchService = Depends(_reference_search_service),
    settings: Settings = Depends(get_settings),
) -> ReferenceSearchResponse:
    """동기 def — 임베딩(외부 호출)을 이벤트 루프 스레드에서 부르지 않는다. 마감은 요청이 들어온 시각부터(검토 2).
    같은 마감을 응답 경계 래퍼(`ResponseDeadlineGuard`)에도 적어 둠 — 응답 시작 때 지났으면 502(검토 3)."""
    received_at = getattr(request.state, RECEIVED_AT, None)
    if received_at is not None:
        setattr(request.state, RESPONSE_DEADLINE, search_deadline(settings, budget_ms, received_at))
    return svc.search(req, budget_ms, received_at)


def _str_index_service(
    session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> StrIndexService:
    return StrIndexService.build(session, settings)


@router.post(
    "/references/str",
    response_model=StrIndexResponse,
    summary="승인 STR 색인 (설계 문서 5.2, SCRUM-310)",
)
def index_approved_str(
    req: StrIndexRequest, svc: StrIndexService = Depends(_str_index_service)
) -> StrIndexResponse:
    """동기 def — 임베딩(외부 호출)을 이벤트 루프 스레드에서 부르지 않는다. 꺼져 있으면 200 SKIPPED·DISABLED(str/03)."""
    return svc.index(req)
