"""facts 분류·집계·입력 확인 — docs/str/04 계산 규칙 표 한 줄 = 테스트 하나. 경로·fact 키는 test_fact_paths.py."""

from __future__ import annotations

from typing import Any

import pytest

from aml_ai.shared.schemas.str import Direction
from aml_ai.str.domain import facts as facts_domain
from tests.str.facts_support import CASES, build, make_req, make_subject, make_txs

# ---------- 분류·집계 ----------


def test_inbound_uses_received_amount_by_currency(mixed) -> None:
    assert mixed.inbound.model_dump() == CASES["mixed"]["expect"]["inbound"]


def test_outbound_uses_paid_amount(mixed) -> None:
    assert mixed.outbound.model_dump() == CASES["mixed"]["expect"]["outbound"]


def test_internal_is_same_entity_and_not_in_flows(mixed) -> None:
    exp = CASES["mixed"]["expect"]["internal"]
    assert mixed.internal.model_dump() == exp
    assert not set(exp["transaction_ids"]) & set(
        mixed.inbound.transaction_ids + mixed.outbound.transaction_ids
    )


def test_indirect_when_subject_not_in_transaction(mixed) -> None:
    assert mixed.indirect.model_dump() == CASES["mixed"]["expect"]["indirect"]


def test_self_transfer_excluded_everywhere(mixed) -> None:
    exp = CASES["mixed"]["expect"]
    assert mixed.excluded_self_transfer_count == exp["excluded_self_transfer_count"]
    self_ids = {
        r["transaction_id"]
        for r in CASES["mixed"]["transactions"]
        if r["from_account_key"] == r["to_account_key"]
    }
    dumped = mixed.model_dump_json()
    assert all(f'"transaction_ids":[{i}]' not in dumped for i in self_ids)


def test_period_is_min_max_of_active_including_indirect(mixed) -> None:
    assert mixed.period.model_dump(mode="json") == CASES["mixed"]["expect"]["period"]


def test_counterparties_distinct_over_inbound_outbound(mixed) -> None:
    assert mixed.counterparties.model_dump() == CASES["mixed"]["expect"]["counterparties"]


def test_direction_and_payment_formats(mixed) -> None:
    assert mixed.direction.value == CASES["mixed"]["expect"]["direction"]
    assert mixed.payment_formats == CASES["mixed"]["expect"]["payment_formats"]


@pytest.mark.parametrize("row", CASES["direction_table"])
def test_direction_table(row: dict[str, Any]) -> None:
    assert facts_domain._direction(row["inbound"], row["outbound"]) is Direction(row["expect"])


def test_subject_typology_and_reporting_institution(mixed) -> None:
    assert mixed.subject.account_key == CASES["subject"]["account_key"]
    assert mixed.subject.entity_name == CASES["subject"]["entity_name"]
    assert mixed.typology_source.value == "RULE"
    req = make_req(CASES["mixed"]["transactions"])
    assert mixed.reporting_institution == req.reporting_institution


def test_reporting_institution_falls_back_to_bank_name() -> None:
    rows = CASES["mixed"]["transactions"]
    req = make_req(rows).model_copy(update={"reporting_institution": None})
    f = facts_domain.build_facts(req, make_txs(rows), make_subject())
    assert f.reporting_institution == CASES["subject"]["bank_name"]


def test_customer_null_when_no_attributes(mixed) -> None:
    assert mixed.customer is None


def test_observations_only_values_and_no_contribution() -> None:
    f = build(CASES["mixed"], reasons=CASES["reasons"])
    assert [o.model_dump(mode="json") for o in f.observations] == CASES["expect_observations"]
    assert f.model_signals == CASES["expect_model_signals"]
    assert "contribution" not in f.model_dump_json()


# ---------- 입력 확인 (application 이 400 으로) ----------


def test_evidence_must_equal_alert_transaction_ids() -> None:
    rows = CASES["mixed"]["transactions"]
    req = make_req(rows, evidence=[r["transaction_id"] for r in rows[:-1]])
    assert facts_domain.request_problem(req) == "evidence must equal alert.transaction_ids"


def test_paths_id_outside_transaction_ids() -> None:
    case = CASES["cycle"]
    outside = max(r["transaction_id"] for r in case["transactions"]) + 1
    req = make_req(case["transactions"], rule_id=case["rule_id"], paths=[*case["paths"], [outside]])
    assert facts_domain.request_problem(req) == "paths id not in transaction_ids"


def test_valid_request_has_no_problem(mixed) -> None:
    assert facts_domain.request_problem(make_req(CASES["mixed"]["transactions"])) is None


def test_self_transfer_only_is_not_reportable() -> None:
    assert not facts_domain.has_reportable(make_txs(CASES["self_transfer_only"]))
    assert facts_domain.has_reportable(make_txs(CASES["mixed"]["transactions"]))


@pytest.mark.parametrize(("name", "code"), list(CASES["currency_names"].items()))
def test_currency_name_to_code(name: str, code: str | None) -> None:
    assert facts_domain.currency_code(name) == code
