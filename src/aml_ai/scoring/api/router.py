"""POST /v1/scores — 500건 묶음, 동기 (규약 3절, 안건 10)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Response

from aml_ai.scoring.application.dl_ranking import ReviewRanking, load_review_ranking
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


@router.get("/dl-rankings/{scan_date}", response_model=ReviewRanking, summary="ML+DL investigation ranking")
def dl_rankings(
    scan_date: date, response: Response, settings: Settings = Depends(get_settings)
) -> ReviewRanking:
    response.headers["Cache-Control"] = "no-store"
    return load_review_ranking(scan_date, settings.ai_dl_snapshot_manifest, settings.ai_dl_snapshot_sha256)
