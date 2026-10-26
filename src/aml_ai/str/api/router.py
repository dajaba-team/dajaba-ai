"""STR 라우터. 백엔드 Controller 와 같은 역할 — 검증·호출·응답만."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.db import get_session
from aml_ai.shared.schemas.str import (
    DraftRequest,
    DraftResponse,
    SummaryRequest,
    SummaryResponse,
    VerifyRequest,
    VerifyResponse,
)
from aml_ai.str.application.draft_service import DraftService
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
