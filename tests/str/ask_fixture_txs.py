"""질문 답변 평가 픽스처의 재현 거래 — build_facts 로 픽스처를 다시 만들어 새 칸(`counterparties_by_direction`)을 얻는다.

SCRUM-358·359 ★B2-1 (A): 픽스처마다 거래 행을 여기 적고, build_facts 결과가 그 픽스처의 **기존 칸 전부와 글자 그대로**
같을 때만 새 칸을 질문 답변 전용 복사본(`facts_ask_<case>.json`)에 쓴다(`test_ask_fixture_rebuild` 가 고정).
fan_in 은 `ops_seed.sql` 거래 1~3 그대로, 나머지는 픽스처 값(합계·min·max·건수·기간·상대·자행·타행·결제 방식·통화)에
맞춰 적은 거래. 대상 계좌 `10_8000EBD30`, 상대 은행 번호는 `10` 이 아니면 타행.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from aml_ai.shared.schemas.str import DraftRequest, Facts
from aml_ai.str.domain import facts as facts_domain
from aml_ai.str.domain.facts_direction import with_direction
from aml_ai.str.domain.models import Customer, Subject, Transaction
from tests.conftest import EXAMPLES, load_json

S = "10_8000EBD30"
_CUSTOMER = Customer(
    industry="RETAIL", risk_level="LOW", account_purpose="SALES_DEPOSIT", onboarded_at=datetime(2021, 3, 14).date(), country_code="PT"
)  # fmt: skip


def _t(
    i: int, ts: str, src: str, dst: str, amount: str, cur: str = "US Dollar", fmt: str = "ACH"
) -> Transaction:
    a = Decimal(amount)
    return Transaction(i, datetime.fromisoformat(ts), src, dst, a, cur, a, cur, fmt, False)


def _reason(name: str, value: float, unit: str | None, start: str | None, end: str | None, basis: str | None,
            baseline: float | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "name": name,
        "observation": {
            "value": value,
            "unit": unit,
            "window_start": start,
            "window_end": end,
            "basis": basis,
        },
        "baseline": {"value": baseline, "definition": None if baseline is None else "평소 기준"},
        "contribution": {"method": "SHAP", "value": 0.42, "scale": "raw_margin"},
    }


_IN_24H = ("account_in_counterparties_24h", 3, "count", "2022-09-02T00:00:00", "2022-09-03T00:00:00",
           "distinct_inbound_counterparties")  # fmt: skip

CASES: dict[str, dict[str, Any]] = {
    "fan_in": {  # ops_seed.sql 거래 1~3 그대로
        "txs": [
            _t(1, "2022-09-02T00:14:00", "020_C0000001", S, "12500.00"),
            _t(2, "2022-09-02T11:30:00", "020_C0000002", S, "14000.00"),
            _t(3, "2022-09-02T22:51:00", "020_C0000003", S, "16250.50"),
        ],
        "rule": ("R02_FAN_IN", "FAN_IN"),
        "reasons": [_reason(*_IN_24H)],
    },
    "fan_out": {
        "txs": [
            _t(1, "2022-09-02T00:14:00", S, "020_C0000001", "12500.00"),
            _t(2, "2022-09-02T11:30:00", S, "020_C0000002", "14000.00"),
            _t(3, "2022-09-02T22:51:00", S, "020_C0000003", "16250.50"),
        ],
        "rule": ("R01_FAN_OUT", "FAN_OUT"),
        "reasons": [
            _reason(
                "distinct_recipients_24h",
                3,
                "count",
                "2022-09-02T00:00:00",
                "2022-09-03T00:00:00",
                "distinct_outbound_counterparties",
            )
        ],  # fmt: skip
    },
    "multi_currency": {
        "txs": [
            _t(1, "2022-09-02T00:14:00", "020_C0000001", S, "12500.00", fmt="ACH"),
            _t(2, "2022-09-03T10:00:00", "030_C0000002", S, "30250.50", fmt="ACH"),
            _t(3, "2022-09-03T15:00:00", "10_C0000003", S, "9800.25", cur="Euro", fmt="Wire"),
            _t(4, "2022-09-04T22:51:30", "040_C0000004", S, "500.00", cur="Peso Uruguay", fmt="Bitcoin"),
        ],
        "rule": ("R02_FAN_IN", "FAN_IN"),
        "prior": 2,
        "customer": Customer(
            industry=None,
            risk_level="HIGH",
            account_purpose="OPERATIONS",
            onboarded_at=None,
            country_code=None,
        ),
        "reasons": [_reason(*_IN_24H), _reason("inflow_ratio_window", 0.75, None, None, None, None)],
    },
    "ask_paths": {  # SCATTER_GATHER — S'→Mᵢ(대상 안 낌 = indirect) · Mᵢ→대상(inbound), 경로 3개
        "txs": [
            _t(1, "2022-09-02T00:20:00", "020_M0000001", S, "12500.00"),
            _t(2, "2022-09-02T11:30:00", "020_M0000002", S, "14000.00"),
            _t(3, "2022-09-02T22:51:00", "020_M0000003", S, "16250.50"),
            _t(4, "2022-09-02T00:14:00", "050_S0000001", "020_M0000001", "12600.00"),
            _t(5, "2022-09-02T11:00:00", "050_S0000001", "020_M0000002", "14100.00"),
            _t(6, "2022-09-02T22:00:00", "050_S0000001", "020_M0000003", "16300.00"),
        ],
        "rule": ("R05_SCATTER_GATHER", "SCATTER_GATHER"),
        "paths": [[4, 1], [5, 2], [6, 3]],
        "reasons": [
            _reason(
                "inflow_outflow_ratio_2h",
                1.0,
                "ratio",
                "2022-09-02T00:00:00",
                "2022-09-02T02:00:00",
                "inflow_minus_outflow",
                baseline=0.4,
            )
        ],  # fmt: skip
    },
    "ask_mixed": {  # 입금 상대 A·B · 출금 상대 B·C·D(겹친 B) — 358 평가 세트 만든 쪽 정답
        "txs": [
            _t(1, "2022-09-03T01:05:00", "020_A0000001", S, "15000.00"),
            _t(2, "2022-09-03T05:00:00", "030_B0000002", S, "12250.50"),
            _t(3, "2022-09-03T09:00:00", S, "030_B0000002", "9000.00"),
            _t(4, "2022-09-03T15:00:00", S, "040_C0000003", "8500.25"),
            _t(5, "2022-09-03T21:40:00", S, "050_D0000004", "7000.00"),
        ],
        "rule": ("R02_FAN_IN", "FAN_IN"),
        "reasons": [
            _reason(
                "account_in_counterparties_24h",
                2,
                "count",
                "2022-09-03T00:00:00",
                "2022-09-04T00:00:00",
                "distinct_inbound_counterparties",
            )
        ],  # fmt: skip
    },
}
# 결제 방식만 다름 — 입금 Wire 2 · 출금 ACH 3(359 세트 만든 쪽 정답)
CASES["ask_mixed_formats"] = {
    **CASES["ask_mixed"],
    "txs": [
        _t(
            t.transaction_id,
            t.ts.isoformat(),
            t.from_account_key,
            t.to_account_key,
            str(t.amount_paid),
            fmt="Wire" if t.to_account_key == S else "ACH",
        )  # fmt: skip
        for t in CASES["ask_mixed"]["txs"]
    ],
}


def rebuild(case: str) -> Facts:
    c = CASES[case]
    txs: list[Transaction] = c["txs"]
    rule_id, typology = c["rule"]
    d = load_json(EXAMPLES / "draft_request.json")
    ids = [t.transaction_id for t in txs]
    d["alert"].update(
        account_key=S,
        rule_id=rule_id,
        typology_hint=typology,
        transaction_ids=ids,
        rule_facts={"paths": c["paths"]} if "paths" in c else {},
    )
    d.update(evidence_transaction_ids=ids, reasons=c["reasons"], prior_alert_count=c.get("prior", 1))
    subject = Subject(
        account_key=S,
        entity_id="80062E240",
        entity_name="Sole Proprietorship #50438",
        bank_name="Portugal Bank #4507",
        entity_type="SOLE_PROPRIETORSHIP",
        customer=c.get("customer", _CUSTOMER),
        account_entities={S: "80062E240"},
    )
    facts = facts_domain.build_facts(DraftRequest.model_validate(d).to_facts_input(), txs, subject)
    return with_direction(facts, txs)  # 질문 답변 서비스와 같은 경로(초안 build_facts 는 칸 안 채움)
