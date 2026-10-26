"""POST /v1/scores — 500건 묶음, 동기 (규약 3절, 안건 10)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from aml_ai.scoring.application.score_service import ScoreService
from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.schemas.alerts import ScoreRequest
from aml_ai.shared.schemas.scores import ScoreResponse

router = APIRouter(tags=["scoring"])


def _service(settings: Settings = Depends(get_settings)) -> ScoreService:
    return ScoreService(settings)


@router.post("/scores", response_model=ScoreResponse, summary="경보 점수 (규약 3절)")
def score(req: ScoreRequest, svc: ScoreService = Depends(_service)) -> ScoreResponse:
    return svc.score(req)
