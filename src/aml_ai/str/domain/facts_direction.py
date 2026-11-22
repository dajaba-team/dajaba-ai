"""방향별 상대 수·자행·타행 (SCRUM-358·359, docs/str/04 `counterparties_by_direction`). 순수 함수.

질문 답변만 그때 계산해 facts 에 붙인다(`with_direction`) — 초안·요약 build_facts 는 안 채움(추가 검토 1 H3 — 저장 행 그대로).

자행·타행은 `counterparty_banks` 와 같은 `{bank_id}` 비교. 정본 규칙은 04, 모양은 shared/schemas/str/facts_direction.py.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CounterpartiesByDirection, DirectionCounterparties, Facts
from aml_ai.str.domain.models import Transaction


def counterparties_by_direction(
    inbound: list[Transaction], outbound: list[Transaction], s: str
) -> CounterpartiesByDirection:
    """inbound = 입금 거래의 보낸 쪽 distinct, outbound = 출금 거래의 받는 쪽 distinct."""
    return CounterpartiesByDirection(
        inbound=_one({t.from_account_key for t in inbound}, s),
        outbound=_one({t.to_account_key for t in outbound}, s),
    )


def _one(others: set[str], s: str) -> DirectionCounterparties:
    s_bank = s.partition("_")[0]
    same = sum(1 for k in others if k.partition("_")[0] == s_bank)
    return DirectionCounterparties(
        count=len(others), same_bank_accounts=same, other_bank_accounts=len(others) - same
    )


def with_direction(facts: Facts, txs: list[Transaction]) -> Facts:
    """facts 의 입금·출금 거래 ID 로 같은 거래 행을 골라 `counterparties_by_direction` 을 붙인 복사본."""
    by_id = {t.transaction_id: t for t in txs}
    inbound = [by_id[i] for i in facts.inbound.transaction_ids]
    outbound = [by_id[i] for i in facts.outbound.transaction_ids]
    side = counterparties_by_direction(inbound, outbound, facts.subject.account_key)
    return facts.model_copy(update={"counterparties_by_direction": side})
