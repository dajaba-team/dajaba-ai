"""재블라인드 후보 풀 — 칸별 격자 파라미터 → 거래 행 → `build_facts` (09 2026-11-17 "SCRUM-265 1/2 — 사전 등록" ⑤).

LLM·DB 0. 관측값은 SCRUM-264 이후 실제 형식(사전 이름·basis model_feature·unit·window·baseline null·기여값 양수),
값은 거래에서 셈. 고객 프로필은 사전 안 코드만.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any

from aml_ai.shared.errors import AiError
from aml_ai.shared.schemas.str import DraftRequest, Facts
from aml_ai.str.domain import facts as facts_domain
from aml_ai.str.domain.models import Customer, Subject
from tests.conftest import EXAMPLES, load_json
from tests.str.facts_support import make_txs

START = datetime(2022, 9, 2, 1, 0)
STEP = timedelta(minutes=37)
AMOUNTS = ("1250.00", "9480.50")
CURRENCIES = ("USD", "EUR")
FORMATS = ("ACH", "Wire")
# (엔티티 유형, 업종, 위험등급, 계좌 목적) — 새 8건이 서로 다른 프로필이 되게 칸 수보다 넉넉히
PROFILES: dict[str, tuple[str, str, str, str]] = {
    "p01": ("SOLE_PROPRIETORSHIP", "RETAIL", "LOW", "SALES_DEPOSIT"),
    "p02": ("CORPORATION", "WHOLESALE", "MEDIUM", "TRADE"),
    "p03": ("CORPORATION", "MANUFACTURING", "LOW", "OPERATIONS"),
    "p04": ("PARTNERSHIP", "SERVICE", "MEDIUM", "BUSINESS_SETTLEMENT"),
    "p05": ("INDIVIDUAL", "OTHER", "LOW", "PERSONAL"),
    "p06": ("CORPORATION", "FINANCE", "HIGH", "INVESTMENT"),
    "p07": ("SOLE_PROPRIETORSHIP", "CONSTRUCTION", "MEDIUM", "PAYROLL"),
    "p08": ("CORPORATION", "REAL_ESTATE", "HIGH", "INVESTMENT"),
    "p09": ("CORPORATION", "TRADING", "MEDIUM", "TRADE"),
    "p10": ("INDIVIDUAL", "OTHER", "HIGH", "PERSONAL"),
}
ENTITY_NAMES = {"SOLE_PROPRIETORSHIP": "Sole Proprietorship", "CORPORATION": "Corporation",
                "PARTNERSHIP": "Partnership", "INDIVIDUAL": "Individual"}  # fmt: skip
CONTRIBUTION = 0.1  # 양수 — facts 거르기 ① 통과


def subject_for(index: int, profile: str) -> Subject:
    entity_type, industry, risk, purpose = PROFILES[profile]
    customer = Customer(industry, risk, purpose, date(2020, 1, 1) + timedelta(days=97 * index), "KR")
    return Subject(f"10_S{index:07d}", f"E-S{index}", f"{ENTITY_NAMES[entity_type]} #{4100 + index}",
                   "Portugal Bank #4507", entity_type, customer)  # fmt: skip


def rows_for(edges: list[tuple[str, str]], amount: str, currency: str, fmt: str) -> list[dict[str, Any]]:
    """(보낸 계좌, 받은 계좌) 순서대로 STEP 간격 거래. 금액은 건마다 조금씩 다르게."""
    return [
        {"transaction_id": 1000 + i, "ts": (START + STEP * i).isoformat(), "from_account_key": frm,
         "to_account_key": to, "amount_paid": f"{float(amount) + i:.2f}", "currency_paid": currency,
         "amount_received": f"{float(amount) + i:.2f}", "currency_received": currency, "payment_format": fmt,
         "is_self_transfer": False}
        for i, (frm, to) in enumerate(edges)
    ]  # fmt: skip


def counts(rows: list[dict[str, Any]], s: str) -> dict[str, float]:
    """거래에서 센 관측값 재료 — 피처 이름 그대로."""
    ins = [r for r in rows if r["to_account_key"] == s]
    outs = [r for r in rows if r["from_account_key"] == s]
    return {
        "focal_distinct_senders": len({r["from_account_key"] for r in ins}),
        "focal_distinct_receivers": len({r["to_account_key"] for r in outs}),
        "focal_in_count": len(ins),
        "focal_out_count": len(outs),
        "evidence_count": len(rows),
        "evidence_account_count": len(
            {k for r in rows for k in (r["from_account_key"], r["to_account_key"])}
        ),
    }


def reason(name: str, value: float) -> dict[str, Any]:
    return {"name": name, "observation": {"value": value, "unit": None, "window_start": None, "window_end": None,
            "basis": "model_feature"}, "baseline": {"value": None, "definition": None},
            "contribution": {"method": "SHAP", "value": CONTRIBUTION, "scale": "raw_margin"}}  # fmt: skip


def build(rows: list[dict[str, Any]], subject: Subject, rule_id: str, typology: str,
          paths: list[list[int]] | None, names: tuple[str, ...]) -> Facts | None:  # fmt: skip
    d = load_json(EXAMPLES / "draft_request.json")
    ids = [r["transaction_id"] for r in rows]
    d["alert"].update(account_key=subject.account_key, entity_id=subject.entity_id, rule_id=rule_id,
                      typology_hint=typology, transaction_ids=ids,
                      rule_facts={"paths": paths} if paths is not None else {})  # fmt: skip
    values = counts(rows, subject.account_key)
    d.update(evidence_transaction_ids=ids, reasons=[reason(n, values[n]) for n in names], prior_alert_count=0)
    try:
        req = DraftRequest.model_validate(d)
        return facts_domain.build_facts(req.to_facts_input(), make_txs(rows), subject)
    except (AiError, ValueError):
        return None


def grid(axes: dict[str, tuple[Any, ...]]) -> Iterator[dict[str, Any]]:
    """칸 축 × 금액·통화·결제 방식·고객 프로필 — 정해진 순서(시드 재현)."""
    base = {"amount": AMOUNTS, "currency": CURRENCIES, "format": FORMATS, "profile": tuple(PROFILES)}
    full = axes | base
    for values in itertools.product(*full.values()):
        yield dict(zip(full, values, strict=True))
