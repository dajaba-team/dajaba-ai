"""build_facts 공통 입력. DraftRequest·SummaryRequest 가 .to_facts_input() 로 변환.

정본 `docs/str/04_facts.md` · `09_decisions.md` 2026-11-06 (SCRUM-129) 결정 줄.
"""

from __future__ import annotations

from pydantic import Field

from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.common import StrictModel, TransactionId
from aml_ai.shared.schemas.scores import Reason


class FactsInput(StrictModel):
    """Facts 조립에 필요한 공통 입력.

    DraftRequest 와 SummaryRequest 가 서로 다른 모양이지만 `build_facts` 입력은 같다 — 이름만 바꾸지
    않고 공통 DTO 를 지나게 해 녹화 키·facts 가 두 자리에서 어긋나지 않는다 (SCRUM-129 ★A 1).
    """

    alert: Alert
    evidence_transaction_ids: list[TransactionId] = Field(min_length=1)
    reasons: list[Reason]
    prior_alert_count: int = Field(ge=0)
    reporting_institution: str | None = None
