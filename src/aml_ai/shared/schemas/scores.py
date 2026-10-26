"""규약 3절 점수 응답. 안건 2·3·4·5 권장안 반영 — 회의 뒤 확정."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from aml_ai.shared.schemas.common import StrictModel, TransactionId


class DataQualityStatus(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class Reason(StrictModel):
    """점수 이유 하나 — 기여값은 method 와 value 쌍 (안건 3)."""

    name: str
    value: float
    method: str = "SHAP"
    baseline: float | None = Field(default=None, description="평소 기준값 — facts.top_reasons 문자열에 쓰임")


class AlertScore(StrictModel):
    alert_id: int
    prediction_id: str | None = Field(default=None, description="ai.predictions PK. 실패 시 None")
    score: float | None = Field(default=None, ge=0, le=1, description="실패 시 None")
    threshold: float
    reasons: list[Reason] = Field(default_factory=list, max_length=3)
    data_quality_status: DataQualityStatus
    evidence_transaction_ids: list[TransactionId] = Field(default_factory=list)


class ScoringMeta(StrictModel):
    model_version: str
    feature_version: str
    server_version: str
    latency_ms: int


class ScoreResponse(StrictModel):
    batch_run_id: int
    scores: list[AlertScore]
    scoring_meta: ScoringMeta
