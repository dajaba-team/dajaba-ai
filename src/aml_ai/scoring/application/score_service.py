"""점수 유스케이스. aml_ml 이 없을 때(AI_SCORING_MOCK) 백엔드 연동용 고정 점수 — 준영이 교체한다 (docs/shared/02)."""

from __future__ import annotations

import time
from datetime import datetime

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.alerts import Alert, ScoreRequest
from aml_ai.shared.schemas.scores import (
    Baseline,
    Contribution,
    DataQualityStatus,
    Observation,
    Reason,
    ScoreItem,
    ScoreResponse,
    ScoringMeta,
)

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
            raise NotImplementedError("준영: aml_ml.score() 연결 — docs/shared/02_ml_package.md")
        return ScoreResponse(
            batch_run_id=req.batch_run_id,
            scores=scores,
            scoring_meta=ScoringMeta(
                model_version=mv,
                feature_version=fv,
                server_version=self._s.server_version,
                latency_ms=int((time.perf_counter() - started) * 1000),
            ),
            produced_at=datetime.now().replace(microsecond=0),
        )

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
