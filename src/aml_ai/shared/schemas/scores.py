"""규약 3절 점수 응답 — v0.2 확정 (안건 2·3·4·5·7, 10/28 준영)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from aml_ai.shared.schemas.common import AlertId, StrictModel, Timestamp, TransactionId


class DataQualityStatus(StrEnum):
    """SHORT_HISTORY·MISSING_INPUT 은 점수가 있는 정상 결과. FAILED 만 점수 없음 (안건 4, shared/02 품질 판정)."""

    OK = "OK"
    SHORT_HISTORY = "SHORT_HISTORY"
    MISSING_INPUT = "MISSING_INPUT"
    FAILED = "FAILED"


class Observation(StrictModel):
    """관측값 — 확인 못 한 값은 null, 0 은 실제 0 을 확인했을 때만."""

    value: float | None
    unit: str | None
    window_start: Timestamp | None
    window_end: Timestamp | None
    basis: str | None


class Baseline(StrictModel):
    value: float | None
    definition: str | None


class Contribution(StrictModel):
    """기여값(SHAP 등). 관측값처럼 쓰지 않는다 — facts 에 들어가지 않는다 (docs/str/04)."""

    method: str | None
    value: float | None
    scale: str | None


class Reason(StrictModel):
    name: str
    observation: Observation
    baseline: Baseline
    contribution: Contribution


class ScoreItem(StrictModel):
    alert_id: AlertId = Field(description="요청값 그대로")
    prediction_id: str | None = Field(description="ai.predictions PK. FAILED 면 null")
    score: float | None = Field(ge=0, le=1, description="조사 우선순위. FAILED 면 null")
    threshold: float = Field(description="추천 임계값. 적용값은 백엔드 CasePolicy")
    data_quality_status: DataQualityStatus
    reasons: list[Reason] = Field(max_length=3, description="상위 3개. 설명만 실패하면 []")
    evidence_transaction_ids: list[TransactionId] = Field(description="경보 안 ⊆ alert.transaction_ids")
    context_transaction_ids: list[TransactionId] = Field(description="경보 밖 참고. STR 에 쓰지 않는다")

    @model_validator(mode="after")
    def _failed_has_no_result(self) -> ScoreItem:
        failed = self.data_quality_status is DataQualityStatus.FAILED
        if failed and (
            self.score is not None
            or self.prediction_id is not None
            or self.reasons
            or self.evidence_transaction_ids
            or self.context_transaction_ids
        ):
            raise ValueError("FAILED item must have score/prediction_id null and empty lists")
        if not failed and (self.score is None or self.prediction_id is None):
            raise ValueError("non-FAILED item must have score and prediction_id")
        return self


class ScoringMeta(StrictModel):
    model_version: str
    feature_version: str
    server_version: str
    latency_ms: int = Field(ge=0)


class ScoreResponse(StrictModel):
    batch_run_id: int
    scores: list[ScoreItem]
    scoring_meta: ScoringMeta
    produced_at: Timestamp
