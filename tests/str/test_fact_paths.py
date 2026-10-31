"""경로(rule_facts.paths) 확인·fact 키·attach_evidence — docs/str/04 "경로"·"fact 키"."""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import LlmNarrativeSection, PathStatus, SectionV1
from aml_ai.str.domain import facts as facts_domain
from aml_ai.str.domain.fact_keys import attach_evidence, fact_keys
from aml_ai.str.domain.masking import mask_for_llm
from aml_ai.str.domain.models import Customer
from tests.str.facts_support import CASES, build, make_req, make_subject, make_txs

# ---------- 경로 ----------


@pytest.mark.parametrize("key", ["cycle", "stack"])
def test_paths_verified(key: str) -> None:
    case = CASES[key]
    f = build(case, rule_id=case["rule_id"], paths=case["paths"])
    exp = {k: v for k, v in case["expect"].items() if k != "indirect_ids"}
    assert f.paths is not None
    assert f.paths.model_dump(mode="json", include=set(exp)) == exp


def test_cycle_middle_hops_are_indirect_not_flows() -> None:
    case = CASES["cycle"]
    f = build(case, rule_id=case["rule_id"], paths=case["paths"])
    assert f.indirect.transaction_ids == case["expect"]["indirect_ids"]
    assert not set(f.indirect.transaction_ids) & set(f.counterparties.transaction_ids)


@pytest.mark.parametrize("name", list(CASES["unverified_cases"]))
def test_paths_unverified(name: str) -> None:
    case = CASES["unverified_cases"][name]
    f = build(case, rule_id=case["rule_id"], paths=case["paths"])
    assert f.paths is not None and f.paths.status is PathStatus.UNVERIFIED


def test_no_paths_is_null(mixed) -> None:
    assert mixed.paths is None


# ---------- fact 키 ----------


def test_fact_keys_amount_key_points_to_that_currency_only(mixed) -> None:
    keys = fact_keys(mixed)
    for c in mixed.inbound.by_currency:
        assert keys[f"inbound.amount.{c.currency}"] == c.transaction_ids


def test_fact_keys_skip_null_facts(mixed) -> None:
    keys = fact_keys(mixed)
    assert not any(k.startswith("customer.") for k in keys)
    assert not any(k.startswith("paths.") for k in keys)
    assert "model_signals" not in keys


def test_fact_keys_paths_only_when_verified() -> None:
    case = CASES["cycle"]
    verified = build(case, rule_id=case["rule_id"], paths=case["paths"])
    assert fact_keys(verified)["paths.count"] == case["expect"]["transaction_ids"]
    bad = CASES["unverified_cases"]["broken_link"]
    unverified = build(bad, rule_id=bad["rule_id"], paths=bad["paths"])
    assert not any(k.startswith("paths.") for k in fact_keys(unverified))


def test_fact_keys_customer_when_present() -> None:
    rows = CASES["mixed"]["transactions"]
    cust = Customer(
        industry="RETAIL", risk_level="LOW", account_purpose=None, onboarded_at=None, country_code="PT"
    )
    f = facts_domain.build_facts(make_req(rows), make_txs(rows), make_subject(cust))
    keys = fact_keys(f)
    assert {"customer.industry", "customer.risk_level", "customer.country_code"} <= set(keys)
    assert "customer.account_purpose" not in keys


def test_attach_evidence_unions_cited_keys_and_ignores_unknown(mixed) -> None:
    keys = fact_keys(mixed)
    usd, eur = (f"inbound.amount.{c.currency}" for c in reversed(mixed.inbound.by_currency))
    sections = [
        LlmNarrativeSection(section=s, text="본문", cites=[usd, eur] if s is SectionV1.SUMMARY else [])
        for s in SectionV1
    ]
    sections[-1] = sections[-1].model_copy(update={"cites": ["subject", "no.such.key"]})
    out = attach_evidence(sections, mixed)
    assert out[0].evidence_ids == sorted(set(keys[usd]) | set(keys[eur]))
    assert out[-1].evidence_ids == []
    assert out[-1].cites == ["subject", "no.such.key"]


def test_mask_drops_indirect_and_unverified_paths() -> None:
    bad = CASES["unverified_cases"]["broken_link"]
    masked = mask_for_llm(build(bad, rule_id=bad["rule_id"], paths=bad["paths"]))
    assert "indirect" not in masked and "paths" not in masked
