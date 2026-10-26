"""build_facts — 정본 docs/str/04_facts.md 의 계산 규칙 표. 순수 함수.

규칙 한 줄 = 테스트 하나 (tests/str/test_facts.py). 바꾸려면 md 먼저.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from aml_ai.shared.schemas.scores import Reason
from aml_ai.shared.schemas.str import CustomerFacts, Direction, DraftRequest, Facts
from aml_ai.str.domain.models import Subject, Transaction


def build_facts(
    req: DraftRequest, txs: list[Transaction], subject: Subject, reasons: list[Reason] | None = None
) -> Facts:
    """경보 + 거래 행 + 대상 → facts. 규칙은 docs/str/04 표.

    TODO(W2): 아래 헬퍼를 채운다. 지금은 시그니처와 조립 순서만.
    """
    active = [t for t in txs if not t.is_self_transfer]  # 자기 계좌 거래는 집계 전체에서 제외
    subject_keys = set(subject.account_keys)

    currency = _base_currency(active)
    base = [t for t in active if t.currency_paid == currency]

    return Facts(
        reporting_institution=req.reporting_institution or subject.bank_name,
        subject_entity_id=subject.entity_id,
        subject_entity_name=subject.entity_name,
        subject_account_keys=list(subject.account_keys),
        period_start=min(t.ts for t in active),
        period_end=max(t.ts for t in active),
        transaction_count=len(active),
        total_amount=_money_str(sum((t.amount_paid for t in base), Decimal(0))),
        currency=currency,
        mixed_currency=len(base) != len(active),
        direction=_direction(active, subject_keys),
        counterparty_count=_counterparty_count(active, subject_keys),
        payment_formats=sorted({t.payment_format for t in active}),
        typology=req.alert.typology,
        typology_source=req.alert.typology_source,
        customer=_customer(subject),
        prior_alert_count=len(req.prior_alerts),  # 내용은 LLM 에 주지 않는다
        top_reasons=_top_reasons(reasons or []),
    )


def _base_currency(txs: list[Transaction]) -> str:
    """건수 최다 currency_paid. 동률이면 금액 합이 큰 쪽 (docs/str/04 결정 사항)."""
    counts = Counter(t.currency_paid for t in txs)
    top = max(counts.values())
    tied = [c for c, n in counts.items() if n == top]
    if len(tied) == 1:
        return tied[0]
    sums = {c: sum((t.amount_paid for t in txs if t.currency_paid == c), Decimal(0)) for c in tied}
    return max(sums, key=lambda c: sums[c])


def _direction(txs: list[Transaction], subject_keys: set[str]) -> Direction:
    inbound = sum(1 for t in txs if t.to_account_key in subject_keys)
    outbound = len(txs) - inbound
    if inbound > outbound:
        return Direction.INBOUND
    if outbound > inbound:
        return Direction.OUTBOUND
    return Direction.MIXED


def _counterparty_count(txs: list[Transaction], subject_keys: set[str]) -> int:
    others = {t.from_account_key if t.to_account_key in subject_keys else t.to_account_key for t in txs}
    return len(others - subject_keys)


def _customer(s: Subject) -> CustomerFacts | None:
    if s.industry is None and s.risk_level is None and s.account_purpose is None and s.onboarded_at is None:
        return None
    return CustomerFacts(
        industry=s.industry,
        risk_level=s.risk_level,
        account_purpose=s.account_purpose,
        onboarded_at=s.onboarded_at,
        country_code=s.country_code,
    )


def _top_reasons(reasons: list[Reason]) -> list[str]:
    """'이름 = 값 (평소 기준값)' 문자열 3개. 점수가 없으면 빈 배열 — 초안은 만든다."""
    out = []
    for r in reasons[:3]:
        base = f" (평소 {r.baseline:g})" if r.baseline is not None else ""
        out.append(f"{r.name} = {r.value:g}{base}")
    return out


def _money_str(x: Decimal) -> str:
    """소수 2자리 고정 문자열. float 금지."""
    return f"{x.quantize(Decimal('0.01')):f}"
