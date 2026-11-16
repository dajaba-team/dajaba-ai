"""test_v4_claims 공용 — 실제 거래 조합으로 build_facts 한 facts·편집자 Plan 생성 (docs/str/08 narrative_v4 3번)."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from datetime import date
from typing import Any

from aml_ai.shared.errors import AiError
from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain.models import Customer
from aml_ai.str.domain.narrative_plan import Candidates, Pick, default_plan, validate_plan
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.facts_support import build, make_subject

LABELS = load_display_labels()
S, S2, A, B, C, Q = (
    "10_S0000001",
    "10_S0000002",
    "020_A0000001",
    "030_B0000001",
    "040_C0000001",
    "10_Q0000001",
)
_CUSTOMER = {
    "industry": "RETAIL",
    "risk_level": "LOW",
    "onboarded_at": date(2021, 3, 14),
    "country_code": "KR",
}
CUSTOMERS: dict[str, Customer | None] = {  # 고객 축 — 계좌 목적 SALES_DEPOSIT·다른 목적·목적 없음·고객 없음
    "sales": Customer(account_purpose="SALES_DEPOSIT", **_CUSTOMER),
    "invest": Customer(account_purpose="INVESTMENT", **_CUSTOMER),
    "no_purpose": Customer(account_purpose=None, **_CUSTOMER),
    "none": None,
}
TYPOLOGIES = ("FAN_IN", "FAN_OUT", "CYCLE", "SCATTER_GATHER", None)  # SCATTER_GATHER → O-HEAD-OTHER·G1


def _tx(tid: int, ts: str, frm: str, to: str) -> dict[str, Any]:
    return {
        "transaction_id": tid, "ts": ts, "from_account_key": frm, "to_account_key": to,
        "amount_paid": "100.00", "currency_paid": "USD", "amount_received": "100.00",
        "currency_received": "USD", "payment_format": "ACH", "is_self_transfer": False,
    }  # fmt: skip


IN, OUT = _tx(1, "2022-09-02T10:00:00", A, S), _tx(2, "2022-09-02T11:00:00", S, Q)  # Q 는 자행 외부 계좌
INTERNAL = _tx(3, "2022-09-03T09:00:00", S2, S)  # 같은 법인 계좌 → 대상(내부 입금), 다음 날
# 내부 거래가 외부와 다른 경우 — 집계(외부 입출금)와 전체 거래가 갈리는 축(추가 검토 4차)
INTERNALS: dict[str, dict[str, Any]] = {
    "same": INTERNAL,
    "small": {**INTERNAL, "amount_paid": "1.00", "amount_received": "1.00"},
    "other": {**INTERNAL, "amount_paid": "1.00", "amount_received": "1.00", "currency_paid": "EUR",
              "currency_received": "EUR", "payment_format": "Wire"},
}  # fmt: skip
CYCLE_TXS = [
    _tx(10, "2022-09-02T13:00:00", S, B),
    _tx(11, "2022-09-02T14:00:00", B, C),
    _tx(12, "2022-09-02T15:00:00", C, S),
]
SG_TXS = [_tx(20, "2022-09-02T13:00:00", A, B), _tx(21, "2022-09-02T14:00:00", B, S)]
PATHS: dict[str, tuple[str, list[dict[str, Any]], list[list[int]] | None]] = {
    "none": ("R02_FAN_IN", [], None),
    "cycle_verified": ("R04_CYCLE", CYCLE_TXS, [[10, 11, 12]]),
    "cycle_unverified": ("R04_CYCLE", CYCLE_TXS, [[11, 10, 12]]),  # 순서가 틀려 UNVERIFIED
    "sg_verified": ("R05_SCATTER_GATHER", SG_TXS, [[20, 21]]),
}


_W0, _W1 = "2022-09-02T00:00:00", "2022-09-03T00:00:00"


def _reason(name: str, value: float | None, baseline: float | None, *, window: tuple = (_W0, _W1)) -> dict:
    return {
        "name": name,
        "observation": {"value": value, "unit": "count", "window_start": window[0], "window_end": window[1], "basis": "distinct_inbound_counterparties"},
        "baseline": {"value": baseline, "definition": "other days mean" if baseline is not None else None},
        "contribution": {"method": "SHAP", "value": 0.1, "scale": "raw_margin"},
    }  # fmt: skip


# 관측값 축 — baseline 조합·관측값 null·관측 구간 한쪽만(부재 주장 검사용)
OBS: dict[str, list[dict]] = {
    "none": [],
    "both": [_reason("a", 3, 2.0), _reason("b", 4, 1.0)],
    "first_only": [_reason("a", 3, 2.0), _reason("b", 4, None)],
    "second_only": [_reason("a", 3, None), _reason("b", 4, 2.0)],
    "zero_and_null": [_reason("a", 3, 0.0), _reason("b", 4, None)],
    "all_null": [_reason("a", 3, None), _reason("b", 4, None)],
    "one_value_null": [_reason("a", None, None), _reason("b", 4, 2.0)],
    "half_window": [_reason("a", 3, 2.0, window=(_W0, None)), _reason("b", 4, None, window=(None, _W1))],
}


def facts_for(  # 축: 흐름·경로·유형 + 고객·과거 경보·관측값
    n_in: int,
    n_out: int,
    n_int: int,
    path: str,
    typology: str | None,
    customer: str = "sales",
    prior: int = 1,
    obs: str = "none",
    internal: str = "same",
) -> Facts | None:
    rule_id, extra, paths = PATHS[path]
    rows = [IN] * n_in + [OUT] * n_out + [INTERNALS[internal]] * n_int + extra
    subject = make_subject(customer=CUSTOMERS[customer])
    try:
        facts = build({"transactions": rows}, subject=subject, rule_id=rule_id, paths=paths, reasons=OBS[obs])
    except (AiError, ValueError):
        return None  # 요청 검증에서 막히는 조합(거래 없음 등)
    update = {"typology": Typology(typology) if typology else None, "prior_alert_count": prior}
    return facts.model_copy(update=update)


_BASE = list(itertools.product((0, 1), (0, 1), (0, 1), PATHS, TYPOLOGIES))
# 기본 조합 전체 + 한 축씩 바꾼 조합(고객 셋·과거 경보 0) — 전부 곱하지 않음
_ARGS = [(*b, "sales", 1) for b in _BASE]
_ARGS += [(*b, c, 1) for b in _BASE for c in ("invest", "no_purpose", "none")]
_ARGS += [(*b, "sales", 0) for b in _BASE]
_ARGS += [(*b, "sales", 1, o) for b in _BASE for o in OBS if o != "none"]
_ARGS += [(*b, "sales", 1, "none", i) for b in _BASE if b[2] == 1 for i in ("small", "other")]
COMBOS = [(args, f) for args in _ARGS if (f := facts_for(*args)) is not None]


def editor_plans(c: Candidates) -> Iterator[dict]:
    """기본 Plan + 편집자 Plan(사유 항목 하나씩·상위 3 × 선택 확인 사항 하나씩 × 변형) — 검증 통과분만."""
    yield default_plan(c)
    required = [i for i in c.checks if i.required]
    optional = [i for i in c.checks if not i.required]
    grounds_opts = [[], *([g] for g in c.grounds), c.grounds[:3]]
    for v in range(max(len(i.variants) for i in c.by_id.values())):
        for g, o in itertools.product(grounds_opts, [[], *([x] for x in optional)]):
            plan = {
                SectionV2.GROUNDS: [Pick(i.id, min(v, len(i.variants) - 1)) for i in g],
                SectionV2.OPINION: [Pick(c.head.id, min(v, 1))]
                + [Pick(i.id, min(v, len(i.variants) - 1)) for i in (*required, *o)],
            }
            if validate_plan(plan, c) == []:
                yield plan
