"""SCRUM-228 — derived 플래그·조립 (docs/str/05 narrative_v4). 카탈로그 조건은 test_v4_grounds_catalog."""

from __future__ import annotations

import copy

import pytest

from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import masking
from aml_ai.str.domain.catalog_types import render_context
from aml_ai.str.domain.constants_v4 import FLAG_SLOT_TEXT
from aml_ai.str.domain.derived_flags import derive_flags, true_flags
from aml_ai.str.domain.display_slots import build_slots
from aml_ai.str.domain.narrative_assembly import AssemblyTooLong, assemble
from aml_ai.str.domain.narrative_plan import candidates, default_plan
from aml_ai.str.domain.slot_types import slot
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.v4_slot_support import load_fixture

BASE = masking.mask_for_llm(load_fixture("facts_fan_in.json"))
LABELS = load_display_labels()


def _with(**changes: object) -> dict:
    d = copy.deepcopy(BASE)
    for path, value in changes.items():
        node = d
        *parents, leaf = path.split("__")
        for p in parents:
            node = node[p]
        node[leaf] = value
    return d


def test_flag_names_match_word_table() -> None:
    assert FLAG_SLOT_TEXT.keys() <= derive_flags(BASE).keys()  # 문장은 single_day 만(05)


@pytest.mark.parametrize(
    ("changes", "flag", "expected"),
    [
        ({}, "all_other_bank", True),
        ({"counterparty_banks__same_bank_accounts": 1}, "all_other_bank", False),
        (
            {"counterparty_banks__other_bank_accounts": 0, "counterparty_banks__same_bank_accounts": 2},
            "all_same_bank",
            True,
        ),
        (
            {"counterparty_banks__other_bank_accounts": 0, "counterparty_banks__same_bank_accounts": 0},
            "all_same_bank",
            False,
        ),
        ({}, "single_day", True),
        ({"period__end": "2022-09-03T00:00:00"}, "single_day", False),
        ({}, "inbound_only", True),
        ({"outbound__count": 1}, "inbound_only", False),
        ({"inbound__count": 0, "outbound__count": 2}, "outbound_only", True),
        ({"inbound__count": 0, "outbound__count": 0}, "outbound_only", False),
    ],
)
def test_flags_boundaries(changes: dict, flag: str, expected: bool) -> None:
    assert derive_flags(_with(**changes))[flag] is expected


def test_true_flags_sorted_only_true() -> None:
    assert true_flags({"b": True, "a": True, "c": False}) == ["a", "b"]


def test_assemble_cites_union_and_too_long() -> None:
    """조립 — 슬롯 cites 와 부품 cites 합집합(순서 유지), 섹션 1,200자 넘으면 AssemblyTooLong."""
    flags = derive_flags(BASE)
    cands = candidates(BASE, flags)
    plan = default_plan(cands)
    ctx = render_context(BASE, LABELS)
    slots = build_slots(BASE, LABELS, flags)
    secs = {s.section: s for s in assemble(slots, plan, cands, ctx)}
    assert [s for s in SectionV2] == list(secs)
    grounds = secs[SectionV2.GROUNDS].cites
    assert grounds[0].startswith("observations.") and "customer.account_purpose" in grounds
    assert len(grounds) == len(set(grounds))
    long_slots = slots | {SectionV2.GROUNDS: [slot("가" * 1190)]}
    with pytest.raises(AssemblyTooLong) as exc:
        assemble(long_slots, plan, cands, ctx)
    assert exc.value.section is SectionV2.GROUNDS
