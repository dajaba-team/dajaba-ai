"""test_facts·test_fact_paths 공용 — fixtures/facts_cases.json 을 도메인 입력으로 바꾼다."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from aml_ai.shared.schemas.str import DraftRequest, Facts
from aml_ai.str.domain import facts as facts_domain
from aml_ai.str.domain.models import Customer, Subject, Transaction
from tests.conftest import EXAMPLES, FIXTURES, load_json

CASES = load_json(FIXTURES / "facts_cases.json")


def make_txs(rows: list[dict[str, Any]]) -> list[Transaction]:
    return [
        Transaction(
            **{
                **r,
                "ts": datetime.fromisoformat(r["ts"]),
                "amount_paid": Decimal(r["amount_paid"]),
                "amount_received": Decimal(r["amount_received"]),
            }
        )
        for r in rows
    ]


def make_subject(customer: Customer | None = None, entity_type: str | None = None) -> Subject:
    return Subject(**CASES["subject"], entity_type=entity_type, customer=customer)


def make_req(
    rows: list[dict[str, Any]],
    *,
    rule_id: str = "R02_FAN_IN_24H",
    paths: list[list[int]] | None = None,
    evidence: list[int] | None = None,
    reasons: list[dict[str, Any]] | None = None,
) -> DraftRequest:
    d = load_json(EXAMPLES / "draft_request.json")
    ids = [r["transaction_id"] for r in rows]
    d["alert"].update(
        account_key=CASES["subject"]["account_key"],
        rule_id=rule_id,
        transaction_ids=ids,
        rule_facts={"paths": paths} if paths is not None else {},
    )
    d["evidence_transaction_ids"] = evidence if evidence is not None else ids
    d["reasons"] = reasons if reasons is not None else []
    return DraftRequest.model_validate(d)


def build(case: dict[str, Any], *, subject: Subject | None = None, **kw: Any) -> Facts:
    rows = case["transactions"]
    return facts_domain.build_facts(make_req(rows, **kw), make_txs(rows), subject or make_subject())
