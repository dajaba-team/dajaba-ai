"""점수 유스케이스. aml_ml 이 없을 때(AI_SCORING_MOCK) 백엔드 연동용 고정 점수 — 준영이 교체한다 (docs/shared/02)."""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from aml_ai.scoring.infrastructure.aml_ml_adapter import AmlMlAdapter, ModelVersion, failed_score
from aml_ai.scoring.infrastructure.prediction_repository import is_registered, save_predictions
from aml_ai.scoring.infrastructure.transaction_reader import HistoryCoverage, read_transactions
from aml_ai.shared.config import Settings
from aml_ai.shared.db import get_engine
from aml_ai.shared.errors import DbUnavailable, ModelUnavailable
from aml_ai.shared.schemas.alerts import Alert, ScoreRequest
from aml_ai.shared.schemas.scores import (
    Baseline,
    Contribution,
    DataQualityStatus,
    FailureCode,
    Observation,
    Reason,
    ScoreItem,
    ScoreResponse,
    ScoringMeta,
)
from aml_ai.shared.time_utils import utc_now
from aml_ai.shared.versioning import set_served_model

MOCK_THRESHOLD = 0.7
MOCK_MODEL_VERSION = "mock-0"
MOCK_FEATURE_VERSION = "mock"
MOCK_SCORE_BUCKETS = 10  # alert_id 끝자리 → 0.05~0.95 (백엔드가 HIGH/LOW 둘 다 보게)


class ScoreService:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def score(self, req: ScoreRequest) -> ScoreResponse:
        started = time.perf_counter()
        if self._s.ai_scoring_mock:
            scores = [self._mock(a) for a in req.alerts]
            mv, fv = MOCK_MODEL_VERSION, MOCK_FEATURE_VERSION
        else:
            scores, version = self._model_scores(req)
            mv, fv = version.model_version, version.feature_version
        return ScoreResponse(
            batch_run_id=req.batch_run_id,
            scores=scores,
            scoring_meta=ScoringMeta(
                model_version=mv,
                feature_version=fv,
                server_version=self._s.server_version,
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
            produced_at=utc_now(),
        )

    def _model_scores(self, req: ScoreRequest) -> tuple[list[ScoreItem], ModelVersion]:
        try:
            try:
                history_bounds = self._s.scoring_history_bounds()
            except ValueError as exc:
                raise ModelUnavailable(
                    "scoring history settings are invalid", history_config_error=str(exc)
                ) from exc
            adapter = AmlMlAdapter.load()
            version = adapter.version
            with Session(get_engine()) as session, session.begin():
                session.execute(text("set transaction isolation level repeatable read"))
                if not is_registered(
                    session,
                    version.model_version,
                    version.feature_version,
                    version.threshold,
                    version.package_version,
                ):
                    raise ModelUnavailable(
                        "scoring model is not registered for serving", package_version=version.package_version
                    )
                adapter.ensure_model_ready()
                rows, coverage = read_transactions(session, req.alerts, history_bounds=history_bounds)
                scores = self._score_batch(adapter, req.alerts, rows, coverage)
                save_predictions(
                    session,
                    scores,
                    batch_run_id=req.batch_run_id,
                    model=version.model_version,
                    feature=version.feature_version,
                )
        except ModelUnavailable:
            set_served_model(None)
            raise
        except SQLAlchemyError as exc:
            raise DbUnavailable(error_type=type(exc).__name__) from exc
        if any(item.score is not None for item in scores):
            set_served_model((version.model_version, version.feature_version))
        return scores, version

    @staticmethod
    def _score_batch(
        adapter: AmlMlAdapter,
        alerts: list[Alert],
        rows: list[dict[str, object]],
        coverage: list[HistoryCoverage | None],
    ) -> list[ScoreItem]:
        present_ids = {row["transaction_id"] for row in rows}
        failed: dict[int, ScoreItem] = {}
        ready_alerts: list[Alert] = []
        ready_coverage: list[HistoryCoverage] = []
        for i, (alert, history) in enumerate(zip(alerts, coverage, strict=True)):
            if not present_ids.issuperset(alert.transaction_ids):
                failed[i] = failed_score(alert, adapter.version, FailureCode.TRANSACTION_NOT_FOUND)
            elif history is None:
                failed[i] = failed_score(alert, adapter.version, FailureCode.REQUIRED_INPUT_MISSING)
            else:
                ready_alerts.append(alert)
                ready_coverage.append(history)

        scored = iter(adapter.score(ready_alerts, rows, ready_coverage) if ready_alerts else [])
        return [failed[i] if i in failed else next(scored) for i in range(len(alerts))]

    @staticmethod
    def _mock(alert: Alert) -> ScoreItem:
        # 결정적: alert_id 끝 6자리 → 0.05~0.95.
        seq = int(alert.alert_id.rsplit("-", 1)[1])
        s = round(0.05 + (seq % MOCK_SCORE_BUCKETS) * 0.1, 2)
        return ScoreItem(
            alert_id=alert.alert_id,
            prediction_id=f"mock-{alert.alert_id}",
            score=s,
            threshold=MOCK_THRESHOLD,
            data_quality_status=DataQualityStatus.OK,
            failure_code=None,
            reasons=[
                Reason(
                    name="mock_feature",
                    observation=Observation(
                        value=None, unit=None, window_start=None, window_end=None, basis=None
                    ),
                    baseline=Baseline(value=None, definition=None),
                    contribution=Contribution(method="MOCK", value=s, scale=None),
                )
            ],
            evidence_transaction_ids=list(alert.transaction_ids),
            context_transaction_ids=[],
        )
