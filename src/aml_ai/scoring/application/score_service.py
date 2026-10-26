"""점수 유스케이스. aml_ml 이 없을 때(AI_SCORING_MOCK) 백엔드 연동용 고정 점수 — 준영이 교체한다 (docs/shared/02)."""

from __future__ import annotations

import time

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.alerts import ScoreRequest
from aml_ai.shared.schemas.scores import AlertScore, DataQualityStatus, Reason, ScoreResponse, ScoringMeta

MOCK_THRESHOLD = 0.7


class ScoreService:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def score(self, req: ScoreRequest) -> ScoreResponse:
        started = time.perf_counter()
        if self._s.ai_scoring_mock:
            scores = [self._mock(a.alert_id, a.evidence_transaction_ids) for a in req.alerts]
            mv, fv = "mock-0", "mock"
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
        )

    @staticmethod
    def _mock(alert_id: int, evidence: list[int]) -> AlertScore:
        # 결정적: alert_id 로 0.05~0.95. 백엔드가 HIGH/LOW 둘 다 보게.
        s = round(0.05 + (alert_id % 10) * 0.1, 2)
        return AlertScore(
            alert_id=alert_id,
            prediction_id=f"mock-{alert_id}",
            score=s,
            threshold=MOCK_THRESHOLD,
            reasons=[Reason(name="mock_feature", value=s, method="MOCK", baseline=0.5)],
            data_quality_status=DataQualityStatus.OK,
            evidence_transaction_ids=evidence,
        )
