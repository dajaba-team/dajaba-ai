"""규약 2절 경보. 점수 요청의 배열 원소이자 STR 요청의 alert."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from aml_ai.shared.schemas.common import AccountKey, AlertId, StrictModel, Timestamp, TransactionId, Typology


class RuleFacts(BaseModel):
    """룰이 계산한 사실. 키는 룰마다 다르다(규약 2절) — 모르는 키를 받는다.

    정해진 키는 paths 하나: R04_CYCLE·R05_STACK 만, 경로별 시간순 거래 ID (10/28 준혁).
    확인 규칙은 facts 쪽(docs/str/04 "경로") — 여기서는 모양만.
    """

    model_config = ConfigDict(extra="allow")

    paths: list[list[TransactionId]] | None = None


class Alert(StrictModel):
    alert_id: AlertId
    account_key: AccountKey = Field(description="경보 대상 계좌 — 경보 단위는 계좌")
    entity_id: str | None = Field(description="화면·STR용. AI 는 피처로 쓰지 않는다")
    rule_id: str = Field(description="규약 2절 룰 ID 그대로, 예 R02_FAN_IN_24H")
    rule_version: str
    typology_hint: Typology | None = Field(description="패턴 라벨이 없는 룰은 null")
    window_start: Timestamp
    window_end: Timestamp
    reference_ts: Timestamp = Field(description="이 시각 이전 거래만 피처에. 보통 window_end")
    transaction_ids: list[TransactionId] = Field(min_length=1, description="창 안에서 룰에 걸린 거래 전부")
    rule_facts: RuleFacts
    created_at: Timestamp


class ScoreRequest(StrictModel):
    """POST /v1/scores — 500건 묶음, 동기 (안건 10)."""

    batch_run_id: int
    alerts: list[Alert] = Field(min_length=1, max_length=500)
