"""SCRUM-47 추가 집계 — counterparty_banks·payment_format_counts·amount_range·unmapped_currencies.

`facts.py` 가 200줄 관문을 넘지 않도록 분리. 전부 순수 함수(시계·DB·설정 없음, docs/str/01).
규칙 정본은 docs/str/04 "계산 규칙". 모양 변경은 shared/schemas/str/facts.py.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from aml_ai.shared.schemas.str import (
    AmountRange,
    CounterpartyBanks,
    PaymentFormatCount,
    UnmappedCurrencyAgg,
)
from aml_ai.str.domain.models import Transaction


def counterparty_banks(flows: list[Transaction], s: str) -> CounterpartyBanks:
    """counterparties 집합 기준 자행/타행 분포 — `account_key` 의 `{bank_id}` 비교.

    `{bank_id}_{account}` 꼴에서 앞 bank_id 가 S 와 같으면 자행, 다르면 타행.
    두 합 = `counterparties.count`(상대 계좌 distinct 수).
    """
    s_bank = s.partition("_")[0]
    others = {t.from_account_key if t.to_account_key == s else t.to_account_key for t in flows}
    same = sum(1 for k in others if k.partition("_")[0] == s_bank)
    return CounterpartyBanks(same_bank_accounts=same, other_bank_accounts=len(others) - same)


def payment_format_counts(flows: list[Transaction]) -> list[PaymentFormatCount]:
    """원본 문자열별 건수(inbound ∪ outbound, self-transfer 제외). 건수 내림차순 → 이름순(동률 안정)."""
    counts: dict[str, int] = defaultdict(int)
    for t in flows:
        counts[t.payment_format] += 1
    return [
        PaymentFormatCount(format=name, count=counts[name])
        for name in sorted(counts, key=lambda n: (-counts[n], n))
    ]


def amount_range(
    inbound: list[Transaction],
    outbound: list[Transaction],
    currency_code_fn,
    money_fn,
) -> list[AmountRange]:
    """통화별 min/max — 매핑된 통화만, 거래마다 그 방향 금액(received/paid) 기준.

    `currency_code_fn` 과 `money_fn` 은 순환 import 피하려고 호출자가 주입(facts.py 가 보유).
    """
    per_cur: dict[str, list[Decimal]] = defaultdict(list)
    for t in inbound:
        iso = currency_code_fn(t.currency_received)
        if iso is not None:
            per_cur[iso].append(t.amount_received)
    for t in outbound:
        iso = currency_code_fn(t.currency_paid)
        if iso is not None:
            per_cur[iso].append(t.amount_paid)
    return [
        AmountRange(currency=cur, min=money_fn(min(per_cur[cur])), max=money_fn(max(per_cur[cur])))
        for cur in sorted(per_cur)
    ]


def unmapped_currencies(
    inbound: list[Transaction],
    outbound: list[Transaction],
    currency_code_fn,
) -> list[UnmappedCurrencyAgg]:
    """flow 거래 중 통화 매핑 안 되는 거래 → 원문 이름별 집계 (SCRUM-47, docs/str/04).

    set 으로 모아 중복 없음(inbound·outbound 는 집합이 분리돼 겹치지 않지만 안전 장치).
    """
    by_name: dict[str, set[int]] = defaultdict(set)
    for t in inbound:
        if currency_code_fn(t.currency_received) is None:
            by_name[t.currency_received].add(t.transaction_id)
    for t in outbound:
        if currency_code_fn(t.currency_paid) is None:
            by_name[t.currency_paid].add(t.transaction_id)
    return [
        UnmappedCurrencyAgg(name=name, count=len(ids), transaction_ids=sorted(ids))
        for name, ids in sorted(by_name.items())
    ]
