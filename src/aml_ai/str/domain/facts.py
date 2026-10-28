"""build_facts — 정본 docs/str/04_facts.md 의 계산 규칙 표. 순수 함수.

대상 계좌 S = alert.account_key 관점으로 inbound / outbound / internal / indirect 를 나누고, 금액은 통화별로
따로 합한다(환산 없음). 경로형 경보 확인은 fact_paths.py, fact 키 → 거래 ID 는 fact_keys.py.
규칙 한 줄 = 테스트 하나 (tests/str/test_facts.py). 바꾸려면 md 먼저.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from decimal import Decimal

from aml_ai.shared.schemas.common import TypologySource
from aml_ai.shared.schemas.scores import Reason
from aml_ai.shared.schemas.str import (
    CurrencyTotal,
    CustomerFacts,
    Direction,
    DraftRequest,
    Facts,
    FlowFacts,
    IdGroupFacts,
    ObservationFacts,
    PeriodFacts,
    SubjectFacts,
)
from aml_ai.str.domain.constants import CURRENCY_CODES, DIRECTION_RATIO, MODEL_SIGNALS_TOP, MONEY_QUANT
from aml_ai.str.domain.fact_paths import build_paths, paths_problem
from aml_ai.str.domain.models import Customer, Subject, Transaction


def currency_code(name: str) -> str | None:
    """IBM 원천 통화 이름 → ISO 코드. 이미 코드면 그대로. 표에 없으면 None (호출자가 에러로)."""
    if name in CURRENCY_CODES.values():
        return name
    return CURRENCY_CODES.get(name)


def request_problem(req: DraftRequest) -> str | None:
    """요청 안의 목록끼리 어긋났는지. 있으면 400 메시지, 없으면 None (docs/str/04 "입력"·"경로" 1번)."""
    if set(req.evidence_transaction_ids) != set(req.alert.transaction_ids):
        return "evidence must equal alert.transaction_ids"
    return paths_problem(req.alert)


def has_reportable(txs: Iterable[Transaction]) -> bool:
    """self-transfer 를 빼고 남는 거래가 있는지. 없으면 쓸 게 없어 400."""
    return any(not t.is_self_transfer for t in txs)


def build_facts(req: DraftRequest, txs: list[Transaction], subject: Subject) -> Facts:
    """경보 + 거래 행 + 대상 → facts. 호출 전에 request_problem·has_reportable 을 통과해야 한다."""
    s = subject.account_key
    active = [t for t in txs if not t.is_self_transfer]
    internal = [t for t in active if _is_internal(t, subject)]
    inbound = [t for t in active if t.to_account_key == s and t not in internal]
    outbound = [t for t in active if t.from_account_key == s and t not in internal]
    indirect = [t for t in active if s not in (t.from_account_key, t.to_account_key)]
    flows = inbound + outbound

    return Facts(
        reporting_institution=req.reporting_institution or subject.bank_name,
        subject=SubjectFacts(entity_id=subject.entity_id, entity_name=subject.entity_name, account_key=s),
        period=PeriodFacts(start=min(t.ts for t in active), end=max(t.ts for t in active)),
        inbound=_flow(inbound, received=True),
        outbound=_flow(outbound, received=False),
        internal=_ids(internal),
        indirect=_ids(indirect),
        paths=build_paths(req.alert, txs, s),
        excluded_self_transfer_count=len(txs) - len(active),
        direction=_direction(len(inbound), len(outbound)),
        counterparties=IdGroupFacts(count=_counterparty_count(flows, s), transaction_ids=_sorted_ids(flows)),
        payment_formats=sorted({t.payment_format for t in flows}),
        typology=req.alert.typology_hint,
        typology_source=TypologySource.RULE,
        customer=_customer(subject.customer),
        prior_alert_count=req.prior_alert_count,
        observations=_observations(req.reasons),
        model_signals=[r.name for r in req.reasons[:MODEL_SIGNALS_TOP]],
    )


def _is_internal(t: Transaction, subject: Subject) -> bool:
    """S 가 낀 거래인데 상대 계좌도 S 의 법인 것 — 법인 안 이동."""
    if subject.entity_id is None or subject.account_key not in (t.from_account_key, t.to_account_key):
        return False
    other = t.to_account_key if t.from_account_key == subject.account_key else t.from_account_key
    return subject.account_entities.get(other) == subject.entity_id


def _flow(txs: list[Transaction], *, received: bool) -> FlowFacts:
    """받은 쪽은 amount_received·currency_received, 보낸 쪽은 amount_paid·currency_paid."""
    totals: dict[str, Decimal] = defaultdict(Decimal)
    ids: dict[str, list[int]] = defaultdict(list)
    for t in txs:
        cur, amt = (t.currency_received, t.amount_received) if received else (t.currency_paid, t.amount_paid)
        totals[cur] += amt
        ids[cur].append(t.transaction_id)
    by_currency = [
        CurrencyTotal(
            currency=cur, total=_money(totals[cur]), count=len(ids[cur]), transaction_ids=sorted(ids[cur])
        )
        for cur in sorted(totals)
    ]
    return FlowFacts(count=len(txs), by_currency=by_currency, transaction_ids=_sorted_ids(txs))


def _ids(txs: list[Transaction]) -> IdGroupFacts:
    return IdGroupFacts(count=len(txs), transaction_ids=_sorted_ids(txs))


def _sorted_ids(txs: Iterable[Transaction]) -> list[int]:
    return sorted({t.transaction_id for t in txs})


def _direction(inbound: int, outbound: int) -> Direction:
    if inbound == 0 and outbound == 0:
        return Direction.INTERNAL
    if inbound >= DIRECTION_RATIO * outbound:
        return Direction.INBOUND
    if outbound >= DIRECTION_RATIO * inbound:
        return Direction.OUTBOUND
    return Direction.MIXED


def _counterparty_count(flows: list[Transaction], s: str) -> int:
    return len({t.from_account_key if t.to_account_key == s else t.to_account_key for t in flows})


def _customer(c: Customer | None) -> CustomerFacts | None:
    if c is None:
        return None
    return CustomerFacts(
        industry=c.industry,
        risk_level=c.risk_level,
        account_purpose=c.account_purpose,
        onboarded_at=c.onboarded_at,
        country_code=c.country_code,
    )


def _observations(reasons: list[Reason]) -> list[ObservationFacts]:
    """관측값만. value 가 null 인 항목은 뺀다. 기여값(contribution)은 넣지 않는다 (안건 3)."""
    return [
        ObservationFacts(
            name=r.name,
            value=r.observation.value,
            unit=r.observation.unit,
            window_start=r.observation.window_start,
            window_end=r.observation.window_end,
            basis=r.observation.basis,
            baseline=r.baseline.value,
        )
        for r in reasons
        if r.observation.value is not None
    ]


def _money(x: Decimal) -> str:
    """소수 2자리 고정 문자열, 천 단위 구분 없음. float 금지."""
    return f"{x.quantize(MONEY_QUANT):f}"
