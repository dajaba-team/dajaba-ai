"""SCRUM-265 (1/2) — 재블라인드 사건 파일 (09 2026-11-17 "SCRUM-265 1/2 — 사전 등록" ③~⑥). LLM·DB 0.

칸 4·3·1 + 회귀 3 + 대조 1 = 12쌍 · 칸 조건은 facts 만(하한·상한 식) · 시드 재현 · 정답은 칸에서.
"""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.schemas.str import Facts
from aml_ai.shared.schemas.str.facts_enums import PathKind, PathStatus
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.v4_blind2_cases import (
    CASES_FILE,
    MIN_INTERMEDIATES,
    MIN_RECEIVERS,
    MIN_SENDERS,
    SEED,
    SLOTS,
    case_facts,
    load_cases,
    pick,
    receiver_bounds,
    sender_bounds,
)

DOC = load_cases()
FACTS = case_facts(DOC)
BY_ID = {c["case_id"]: c for c in DOC["cases"]}
JUDGED = [c for c in DOC["cases"] if c["role"] == "judged"]
NAMES = load_display_labels()["observation_name"]


def _verified(f: Facts, kind: PathKind) -> bool:
    return f.paths is not None and f.paths.status is PathStatus.VERIFIED and f.paths.kind is kind


def test_file_is_reproduced_from_seed() -> None:
    """파일 = pick(SEED) 그대로 — 손으로 고치거나 다시 뽑지 않음."""
    assert DOC["seed"] == SEED == 265
    assert json.loads(CASES_FILE.read_text(encoding="utf-8")) == pick(SEED)


def test_other_seed_picks_differently() -> None:
    def chosen(doc: dict) -> list:
        return [(c["case_id"], c["params"]) for c in doc["cases"] if c["role"] == "judged"]

    assert chosen(pick(SEED + 1)) != chosen(DOC)


def test_twelve_pairs_by_slot() -> None:
    slots = [c["slot"] for c in DOC["cases"]]
    assert slots.count("supported") == 4 and slots.count("unsupported") == 3
    assert slots.count("mixed") == 1 and slots.count("regression") == 3
    assert len(DOC["cases"]) + 1 == 12  # 대조쌍 1
    assert DOC["control_case_id"] in {c["case_id"] for c in JUDGED}
    assert {c["case_id"] for c in DOC["cases"] if c["role"] == "regression"} == {
        "reg_fan_in",
        "reg_scatter_gather",
        "reg_customer_missing",
    }
    assert set(DOC["candidate_counts"]) == {s.case_id for s in SLOTS}
    assert all(DOC["candidate_counts"][c["case_id"]] >= 2 for c in JUDGED)  # 시드로 고를 여지


@pytest.mark.parametrize("slot", SLOTS, ids=lambda s: s.case_id)
def test_slot_condition_holds_on_facts(slot) -> None:
    f = FACTS[slot.case_id]
    assert slot.condition(f)
    assert f.typology is not None and f.typology.value == slot.typology == BY_ID[slot.case_id]["typology"]


def test_supported_cases_by_facts_only() -> None:
    lo, _ = sender_bounds(FACTS["sup_fan_in"])
    assert lo >= MIN_SENDERS and FACTS["sup_fan_in"].outbound.count == 0
    assert receiver_bounds(FACTS["sup_fan_out"])[0] >= MIN_RECEIVERS
    assert _verified(FACTS["sup_cycle"], PathKind.CYCLE)
    sg = FACTS["sup_scatter_gather"]
    assert _verified(sg, PathKind.SCATTER_GATHER) and sg.paths is not None
    assert sg.paths.count >= MIN_INTERMEDIATES


def test_mixed_case_sender_lower_bound() -> None:
    """혼재: 출금이 있어도 송금인 하한(counterparties − outbound) ≥ 5 — 2/2 에서 뒷받침됨이어야 정답 "예"와 맞음."""
    f = FACTS["mix_fan_in"]
    assert f.outbound.count >= 1 and f.inbound.count >= 1
    assert f.counterparties.count - f.outbound.count >= MIN_SENDERS
    assert sender_bounds(f)[0] >= MIN_SENDERS


def test_unsupported_cases_lower_bound_or_path_not_verified() -> None:
    """미확인·불충족: 하한 < 5(상한도 < 5) 또는 경로 VERIFIED 아님."""
    f = FACTS["uns_fan_in"]
    assert f.counterparties.count - f.outbound.count < MIN_SENDERS
    assert sender_bounds(f)[1] < MIN_SENDERS
    cycle = FACTS["uns_cycle"]
    assert cycle.paths is None or cycle.paths.status is not PathStatus.VERIFIED
    sg = FACTS["uns_scatter_gather"]
    assert sg.outbound.count == 0 and sg.paths is None


def test_bounds_bracket_real_counts() -> None:
    """하한 ≤ 실제 상대 수 ≤ 상한 — 생성 파라미터(실제 송금인·수취인 수)로 확인."""
    for c in JUDGED:
        f, p = FACTS[c["case_id"]], c["params"]
        lo, hi = sender_bounds(f)
        assert lo <= p["senders"] <= hi, c["case_id"]
        lo, hi = receiver_bounds(f)
        assert lo <= p["receivers"] <= hi, c["case_id"]


def test_answers_come_from_slot() -> None:
    for c in DOC["cases"]:
        want = {"supported": ["yes"], "mixed": ["yes"], "unsupported": ["no", "unknown"], "regression": None}
        assert c["answer"] == want[c["slot"]], c["case_id"]


def test_new_cases_have_distinct_customers() -> None:
    assert len({c["profile"] for c in JUDGED}) == len(JUDGED) == 8
    keys = [FACTS[c["case_id"]].subject.account_key for c in JUDGED]
    ids = [FACTS[c["case_id"]].subject.entity_id for c in JUDGED]
    assert len(set(keys)) == len(set(ids)) == 8


@pytest.mark.parametrize("case_id", sorted(BY_ID))
def test_observations_in_real_format(case_id: str) -> None:
    """SCRUM-264 이후 형식 — 사전 20개 안 이름·basis model_feature·unit·window·baseline null."""
    f = FACTS[case_id]
    assert f.observations
    for o in f.observations:
        assert o.name in NAMES and o.basis == "model_feature"
        assert o.unit is None and o.window_start is None and o.window_end is None and o.baseline is None
    assert set(f.model_signals) <= set(NAMES)


def test_regression_observations_match_transactions() -> None:
    f = FACTS["reg_customer_missing"]
    values = {o.name: o.value for o in f.observations}
    assert values == {"focal_distinct_senders": 1.0, "evidence_count": 2.0}
    assert f.inbound.count == 1 and f.outbound.count == 1 and f.customer is None


def test_observation_values_match_transactions() -> None:
    for c in JUDGED:
        values = {o.name: o.value for o in FACTS[c["case_id"]].observations}
        if "focal_distinct_senders" in values:
            assert values["focal_distinct_senders"] == c["params"]["senders"], c["case_id"]
        if "focal_distinct_receivers" in values:
            assert values["focal_distinct_receivers"] == c["params"]["receivers"], c["case_id"]
