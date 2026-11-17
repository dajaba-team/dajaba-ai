"""SCRUM-228 — 카탈로그 전제(requires) 일반 검사 + 구조 변경 뒤 추가 검토 1차 반례 회귀 (docs/str/05 "requires", 08 3번).

모든 항목 × 그 항목의 전제 하나씩을 거짓으로 → 후보에서 빠짐(기본 Plan), 편집자 Plan 에 넣으면 unknown_item.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str import Facts
from aml_ai.shared.schemas.str.facts_enums import PathStatus
from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import masking
from aml_ai.str.domain.catalog_types import render_context
from aml_ai.str.domain.constants_v4 import PREMISES
from aml_ai.str.domain.derived_flags import derive_flags
from aml_ai.str.domain.display_slots import build_slots
from aml_ai.str.domain.grounds_catalog import GROUNDS_ITEMS
from aml_ai.str.domain.narrative_assembly import assemble
from aml_ai.str.domain.narrative_plan import Pick, candidates, default_plan, validate_plan
from aml_ai.str.domain.opinion_catalog import CHECK_ITEMS
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.narrative_v4_builder import build_v4
from tests.str.facts_support import CASES, build
from tests.str.v4_slot_support import facts_sources, failures, load_fixture

LABELS = load_display_labels()
ITEMS = [*GROUNDS_ITEMS, *CHECK_ITEMS]

_FALSIFY: dict[str, Callable[[dict[str, Any]], None]] = {
    "has_inbound": lambda f: f["inbound"].update(count=0, by_currency=[]),
    "has_outbound": lambda f: f["outbound"].update(count=0, by_currency=[]),
    "has_counterparty": lambda f: f["counterparties"].update(count=0),
    "path_verified": lambda f: f.pop("paths", None),
    "cycle_verified": lambda f: f["paths"].update(kind="SCATTER_GATHER"),  # 확인됐지만 비순환
    "has_purpose": lambda f: f["customer"].update(account_purpose=None),
    "has_customer": lambda f: f.update(customer=None),
    "has_prior": lambda f: f.update(prior_alert_count=0),
    "has_same_bank": lambda f: f["counterparty_banks"].update(same_bank_accounts=0),
    "typology_supported": lambda f: f.update(typology=None),  # 판정 없음(SCRUM-265 2/2)
    "typology_unsupported": lambda f: f.update(typology=None),
}


def _pool() -> list[dict[str, Any]]:
    """항목마다 후보가 되는 facts 를 찾을 풀 — 픽스처·few-shot 마스킹본 + 같은 은행·유형 변형."""
    base = [masking.mask_for_llm(f) for _, f in facts_sources()]
    extra = []
    for f in base:
        for typology in ("FAN_IN", "FAN_OUT", "CYCLE", None):
            d = copy.deepcopy(f)
            d["typology"] = typology
            d["counterparty_banks"]["same_bank_accounts"] = 1
            if d["customer"] is not None:
                d["customer"]["account_purpose"] = "SALES_DEPOSIT"
            extra.append(d)
    return base + extra


def _ids(f: dict[str, Any]) -> set[str]:
    c = candidates(f, derive_flags(f))
    return {i.id for i in (*c.grounds, *c.checks)}


def test_premise_names_are_closed() -> None:
    assert {p for i in ITEMS for p in i.requires} <= set(PREMISES)
    assert set(_FALSIFY) == set(PREMISES)


@pytest.mark.parametrize(
    ("item_id", "premise"), [(i.id, p) for i in ITEMS for p in i.requires], ids=lambda x: str(x)
)
def test_false_premise_removes_item(item_id: str, premise: str) -> None:
    base = next((f for f in _pool() if item_id in _ids(f)), None)
    assert base is not None, f"{item_id} 가 후보가 되는 facts 가 풀에 없음"
    broken = copy.deepcopy(base)
    _FALSIFY[premise](broken)
    assert item_id not in _ids(broken)
    flags = derive_flags(broken)
    c = candidates(broken, flags)
    plan = default_plan(c)
    section = SectionV2.GROUNDS if item_id.startswith("G-") else SectionV2.OPINION
    assert item_id not in {p.item_id for p in plan[section]}
    plan[section] = [*plan[section], Pick(item_id)]  # 편집자가 넣어도 거부
    assert "unknown_item" in validate_plan(plan, c)


def _cycle(status: PathStatus | None) -> dict[str, Any]:
    facts = load_fixture("facts_cycle_nopaths.json")
    if status is not None:
        paths = {
            "kind": "CYCLE",
            "status": status,
            "count": 1,
            "max_hops": 3,
            "max_accounts": 3,
            "transaction_ids": [1, 2],
        }
        facts = Facts.model_validate({**facts.model_dump(mode="json"), "paths": paths})
    return masking.mask_for_llm(facts)


@pytest.mark.parametrize("status", [None, PathStatus.UNVERIFIED])
def test_unverified_cycle_has_no_return_claims(status: PathStatus | None) -> None:
    """추가 검토 반례 1 — 경로 없음·UNVERIFIED 면 Y1·Y2 없음, "돌아온" 문장 없음, 새 문구."""
    f = _cycle(status)
    assert not {"Y1", "Y2"} & _ids(f)
    text = " ".join(s.text for s in build_v4(f, LABELS))
    assert "돌아온" not in text
    assert (
        "자금 순환(CYCLE) 분류를 뒷받침하는 경로" in text
    )  # 판정 미확인 문장(SCRUM-265 2/2 — G-CYCLE-PATH 대신)


def test_verified_cycle_keeps_y1_y2_and_drops_path_unconfirmed() -> None:
    f = _cycle(PathStatus.VERIFIED)
    assert {"Y1", "Y2"} <= _ids(f) and "Y3" not in _ids(f) and "G-CYCLE-PATH" not in _ids(f)


def _internal_only(typology: str | None) -> tuple[Facts, dict[str, Any]]:
    tx4 = next(t for t in CASES["mixed"]["transactions"] if t["transaction_id"] == 4)
    facts = build({"transactions": [tx4]}).model_copy(
        update={"typology": Typology(typology) if typology else None}
    )
    return facts, masking.mask_for_llm(facts)


@pytest.mark.parametrize("typology", ["FAN_IN", "FAN_OUT", None])
def test_internal_only_alert_has_no_flow_or_counterparty_claims(typology: str | None) -> None:
    """추가 검토 반례 2 — 입금=출금=상대=0 이면 "위 입금"·F*·G1·G-COUNTERPARTY 없음, 첫 문장 "위 거래"."""
    facts, f = _internal_only(typology)
    assert (f["inbound"]["count"], f["outbound"]["count"], f["counterparties"]["count"]) == (0, 0, 0)
    gone = {"F1", "F2", "F3", "O1", "O2", "O3", "G1", "G-COUNTERPARTY", "G-PURPOSE-IN", "G-PURPOSE-OUT"}
    assert not gone & _ids(f)
    sections = {s.section: s.text for s in build_v4(f, LABELS)}
    assert "위 입금" not in " ".join(sections.values())
    assert "해당 상대 계좌" not in " ".join(sections.values())
    assert "위 출금" not in " ".join(sections.values())
    heads = {
        "FAN_IN": "자금 집중 유형으로 분류된 위 거래에 대해",
        "FAN_OUT": "자금 분산 유형으로 분류된 위 거래에 대해",
    }
    if typology in heads:
        assert sections[SectionV2.OPINION].startswith(heads[typology])
    assert failures(facts, build_v4(f, LABELS)) == []


def test_unverified_cycle_every_variant_avoids_not_provided() -> None:
    """paths UNVERIFIED 는 자료가 왔는데 확인이 안 된 것 — 모든 항목·변형·짧은 꼴·묶기에 "제공되지 않" 없음."""
    f = _cycle(PathStatus.UNVERIFIED)
    flags = derive_flags(f)
    c = candidates(f, flags)
    slots, ctx = build_slots(f, LABELS, flags), render_context(f, LABELS)
    for v in range(max(len(i.variants) for i in c.by_id.values())):
        plan = {
            SectionV2.GROUNDS: [Pick(i.id, min(v, len(i.variants) - 1)) for i in c.grounds],
            SectionV2.OPINION: [Pick(c.head.id, min(v, 1))]
            + [Pick(i.id, min(v, len(i.variants) - 1)) for i in c.checks],
        }
        text = " ".join(s.text for s in assemble(slots, plan, c, ctx))
        assert "제공되지 않" not in text, v
