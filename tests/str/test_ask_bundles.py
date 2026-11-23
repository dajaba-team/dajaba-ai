"""질문 답변 묶음 → 마스킹 facts 조각 + 인용 키 (SCRUM-290, 정본 docs/str/04 "질문 답변 묶음" — 표 한 줄 = 테스트 하나)."""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain.ask_bundles import ask_fact_keys, extract
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json

RULE = "R02_FAN_IN"


@pytest.fixture
def facts() -> Facts:
    return Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))


def _with(facts: Facts, **changes) -> Facts:
    return Facts.model_validate({**facts.model_dump(mode="json"), **changes})


def _piece(facts: Facts, *bundles: str):
    return extract(facts, RULE, list(bundles), load_display_labels())


def test_subject_piece_and_keys(facts: Facts) -> None:
    p = _piece(facts, "subject")
    assert p.content["subject"]["account_key"] == "10_****BD30"
    assert p.content["customer"]["industry"] == "RETAIL"
    assert p.content["prior_alert_count"] == 1
    assert p.content["reporting_institution"] == "Portugal Bank #4507"
    assert p.keys == (
        "subject",
        "subject.account_key",
        "subject.entity_name",
        "subject.entity_type",
        "customer.industry",
        "customer.risk_level",
        "customer.account_purpose",
        "customer.onboarded_at",
        "customer.country_code",
        "prior_alert_count",
    )


def test_subject_without_customer_has_no_customer_keys(facts: Facts) -> None:
    p = _piece(_with(facts, customer=None), "subject")
    assert not any(k.startswith("customer.") for k in p.keys)
    assert p.content["customer"] is None


def test_flows_piece_and_keys(facts: Facts) -> None:
    p = _piece(facts, "flows")
    assert set(p.content) >= {"period", "inbound", "outbound", "internal", "amount_range", "direction"}
    assert "unmapped_currencies" in p.content
    assert p.keys == (
        "period",
        "inbound.count",
        "inbound.amount.USD",
        "outbound.count",
        "internal.count",
        "amount_range.USD.min",
        "amount_range.USD.max",
        "direction",
        "compare.count",  # (B1) 비교 자리표 — 질문 답변 인용 키(USD 는 출금이 없어 금액 비교 없음)
    )


def test_counterparties_piece_and_keys(facts: Facts) -> None:
    p = _piece(facts, "counterparties")
    assert set(p.content) == {"counterparties", "counterparty_banks"}  # 코드값 없음 → labels 칸 없음
    assert p.keys == (
        "counterparties.count",
        "counterparty_banks.same_bank_accounts",
        "counterparty_banks.other_bank_accounts",
    )


def test_formats_piece_and_keys(facts: Facts) -> None:
    p = _piece(facts, "formats")
    assert p.content["payment_formats"] == ["ACH"]
    assert p.content["payment_format_counts"] == [{"format": "ACH", "count": 3}]
    assert p.keys == ("payment_format_counts.ACH", "direction", "payment_formats")


def test_paths_unverified_is_empty_piece(facts: Facts) -> None:
    p = _piece(facts, "paths")
    assert "paths" not in p.content
    assert p.keys == ()


def test_paths_verified_piece_and_keys(facts: Facts) -> None:
    paths = {"kind": "SCATTER_GATHER", "status": "VERIFIED", "count": 2, "max_hops": 3, "max_accounts": 4}
    p = _piece(_with(facts, paths={**paths, "transaction_ids": [1, 2]}), "paths")
    assert p.content["paths"] == {"kind": "SCATTER_GATHER", "count": 2, "max_hops": 3, "max_accounts": 4}
    assert p.keys == ("paths.count", "paths.max_hops", "paths.max_accounts", "paths.kind")


def test_observations_without_baseline(facts: Facts) -> None:
    p = _piece(facts, "observations")
    (obs,) = p.content["observations"]
    assert set(obs) == {"name", "value", "unit", "window_start", "window_end", "basis"}
    assert "model_signals" not in p.content
    assert p.keys == ("observations.account_in_counterparties_24h",)


def test_score_reasons_with_baseline_and_model_signals(facts: Facts) -> None:
    p = _piece(facts, "score_reasons")
    (obs,) = p.content["observations"]
    assert set(obs) == {"name", "value", "unit", "baseline"}
    assert p.content["model_signals"] == ["account_in_counterparties_24h"]
    assert p.keys == ("observations.account_in_counterparties_24h", "model_signals")


def test_observations_and_score_reasons_union_fields(facts: Facts) -> None:
    p = _piece(facts, "observations", "score_reasons")
    (obs,) = p.content["observations"]
    assert set(obs) == {"name", "value", "unit", "window_start", "window_end", "basis", "baseline"}
    assert len(p.keys) == len(set(p.keys))


def test_rule_facts_piece_and_keys(facts: Facts) -> None:
    p = _piece(facts, "rule_facts")
    assert p.content["typology"] == "FAN_IN"
    assert p.content["typology_source"] == "RULE"
    assert p.content["rule_id"] == RULE
    assert "period" in p.content
    assert p.keys == ("period", "typology")


def test_shared_fields_appear_once(facts: Facts) -> None:
    p = _piece(facts, "flows", "formats", "rule_facts")
    assert p.keys.count("direction") == 1
    assert p.keys.count("period") == 1
    assert p.bundles == ("flows", "formats", "rule_facts")


def test_never_includes_ids_indirect_self_transfer_or_alert_rule_facts(facts: Facts) -> None:
    every = (
        "subject",
        "flows",
        "counterparties",
        "formats",
        "paths",
        "observations",
        "score_reasons",
        "rule_facts",
    )
    for name in every:
        dumped = json.dumps(_piece(facts, name).content, ensure_ascii=False)
        assert "transaction_ids" not in dumped
        assert "indirect" not in dumped
        assert "excluded_self_transfer_count" not in dumped
        assert "contribution" not in dumped
        assert "window_start" not in dumped or name == "observations"


def test_keys_are_subset_of_fact_keys_in_order(facts: Facts) -> None:
    all_keys = list(ask_fact_keys(facts))  # 질문 답변 인용 키(초안 fact_keys + 방향·비교, SCRUM-358·362)
    p = _piece(facts, "subject", "flows", "counterparties")
    assert set(p.keys) <= set(all_keys)


def test_unknown_bundle_raises(facts: Facts) -> None:
    with pytest.raises(ValueError):
        _piece(facts, "nope")


def test_labels_for_codes_in_piece_but_not_currency(facts: Facts) -> None:
    p = _piece(facts, "subject", "formats", "rule_facts")
    labels = p.content["labels"]
    assert labels["industry"] == {"RETAIL": "소매업"}
    assert labels["risk_level"] == {"LOW": "낮음"}
    assert labels["payment_format"] == {"ACH": "ACH"}
    assert labels["typology"]["FAN_IN"]
    assert labels["entity_type"]["SOLE_PROPRIETORSHIP"]
    assert "currency" not in labels


def test_observation_labels(facts: Facts) -> None:
    labels = _piece(facts, "observations").content["labels"]
    assert labels["observation_name"] == {
        "account_in_counterparties_24h": "대상 계좌에 송금한 서로 다른 계좌 수"
    }
    assert labels["observation_unit"] == {"count": "개"}
    assert "observation_basis" in labels
