"""facts `counterparties_by_direction` — 방향별 상대 수·자행·타행 (SCRUM-358·359, docs/str/04). facts.py 200줄 때문에 분리.

질문 답변 전용 — LLM 마스킹본(`mask_for_llm`)·초안 `fact_keys` 에는 없다. 이 칸 전 저장분은 `null`.
"""

from __future__ import annotations

from pydantic import Field

from aml_ai.shared.schemas.common import StrictModel


class DirectionCounterparties(StrictModel):
    """한 방향의 상대 계좌 distinct 수 + 그 자행·타행 분포(두 합 = count)."""

    count: int = Field(ge=0)
    same_bank_accounts: int = Field(ge=0)
    other_bank_accounts: int = Field(ge=0)


class CounterpartiesByDirection(StrictModel):
    """inbound = 입금 거래의 보낸 쪽, outbound = 출금 거래의 받는 쪽. 한 계좌가 양쪽이면 양쪽에 셈."""

    inbound: DirectionCounterparties
    outbound: DirectionCounterparties
