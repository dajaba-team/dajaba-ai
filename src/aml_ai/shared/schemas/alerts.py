"""규약 2절 경보. 점수 요청의 배열 원소이자 STR 요청의 alert."""

from __future__ import annotations

from pydantic import Field

from aml_ai.shared.schemas.common import (
    AccountKey,
    StrictModel,
    Timestamp,
    TransactionId,
    Typology,
    TypologySource,
)


class Alert(StrictModel):
    alert_id: int
    rule_id: str = Field(description="규약 2절 룰 ID 그대로, 예 R02_FAN_IN_24H")
    account_key: AccountKey
    reference_ts: Timestamp = Field(description="창의 끝 = window_end (안건 20)")
    window_start: Timestamp
    evidence_transaction_ids: list[TransactionId] = Field(min_length=1)
    typology: Typology
    typology_source: TypologySource = TypologySource.RULE


class ScoreRequest(StrictModel):
    """POST /v1/scores — 500건 묶음, 동기 (안건 10)."""

    batch_run_id: int
    alerts: list[Alert] = Field(min_length=1, max_length=500)
