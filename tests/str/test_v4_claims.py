"""SCRUM-228 — 주장 → facts 역방향 검사 (docs/str/08 narrative_v4 3번, 09 구조 변경 뒤 추가 검토 2차).

렌더된 문장 속 주장 낱말마다 facts 에서 참이어야 하는 조건을 두고, 실제 거래로 build_facts 한 조합 전부에서
기본 Plan + 편집자 Plan(항목·변형·짧은 꼴 — validate_plan 통과분)을 렌더해 검사한다.
"""

from __future__ import annotations

import re

import pytest

from aml_ai.shared.schemas.str import Facts, PathStatus
from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import masking
from aml_ai.str.domain.catalog_types import render_context
from aml_ai.str.domain.derived_flags import derive_flags
from aml_ai.str.domain.display_slots import build_slots
from aml_ai.str.domain.narrative_assembly import assemble
from aml_ai.str.domain.narrative_plan import Pick, candidates, default_plan, validate_plan
from tests.str.v4_claims_support import COMBOS, CUSTOMERS, LABELS, PATHS, editor_plans, facts_for
from tests.str.v4_claims_table import CLAIMS, OBS_CLAIMS
from tests.str.v4_slot_support import failures


def test_combos_cover_paths_and_flows() -> None:
    assert len(COMBOS) > 1500
    assert {a[3] for a, _ in COMBOS} == set(PATHS)
    assert {a[5] for a, _ in COMBOS} == set(CUSTOMERS) and {a[6] for a, _ in COMBOS} == {0, 1}


def test_net_actually_renders_every_item_kind() -> None:
    """그물에 실제로 걸렸는지 — C1·C2·G1·O-HEAD-OTHER·F2·O3 가 조합 렌더 어딘가에 최소 한 번 나옴."""
    seen: set[str] = set()
    for _, facts in COMBOS:
        masked = masking.mask_for_llm(facts)
        c = candidates(masked, derive_flags(masked))
        for plan in editor_plans(c):
            seen |= {p.item_id for picks in plan.values() for p in picks}
    assert {"C1", "C2", "G1", "O-HEAD-OTHER", "F2", "O3", "Y1", "Y2", "Y3", "B1"} <= seen


@pytest.mark.parametrize(("args", "facts"), COMBOS, ids=[str(a) for a, _ in COMBOS])
def test_every_claim_word_holds_in_facts(args: tuple, facts: Facts) -> None:
    masked = masking.mask_for_llm(facts)
    flags = derive_flags(masked)
    c = candidates(masked, flags)
    slots, ctx = build_slots(masked, LABELS, flags), render_context(masked, LABELS)
    for plan in editor_plans(c):
        text = " ".join(s.text for s in assemble(slots, plan, c, ctx))
        for word, holds in CLAIMS.items():
            if re.search(word, text):
                assert holds(facts), (args, word)
        for phrase in OBS_CLAIMS:  # 관측값 단위 주장은 관측값 문장 밖에 안 나옴
            inside = sum(
                s.text.count(phrase)
                for s in slots[SectionV2.GROUNDS]
                if s.cites and s.cites[0].startswith("observations.")
            )
            assert text.count(phrase) == inside, (args, phrase)
    by_name = {o.name: o for o in facts.observations}
    for s in slots[SectionV2.GROUNDS]:
        if s.cites and s.cites[0].startswith("observations."):
            o = by_name[s.cites[0].removeprefix("observations.")]
            for phrase, holds in OBS_CLAIMS.items():
                if phrase in s.text:
                    assert holds(o, facts), (args, o.name, phrase)


@pytest.mark.parametrize(("args", "facts"), COMBOS, ids=[str(a) for a, _ in COMBOS])
def test_every_combo_passes_code_checks(args: tuple, facts: Facts) -> None:
    """조합 전부(기본 Plan) — 06 코드 검사 UNPARSED·MISMATCH 0. 관측 구간 한쪽·관측값 단위 기준값 문장 포함."""
    masked = masking.mask_for_llm(facts)
    flags = derive_flags(masked)
    c = candidates(masked, flags)
    sections = assemble(
        build_slots(masked, LABELS, flags), default_plan(c), c, render_context(masked, LABELS)
    )
    assert [(f.check, f.section, f.reason) for f in failures(facts, sections)] == [], args


def _ids(facts: Facts) -> set[str]:
    masked = masking.mask_for_llm(facts)
    c = candidates(masked, derive_flags(masked))
    return {i.id for i in (*c.grounds, *c.checks)}


def test_scatter_gather_verified_with_cycle_label_has_no_return_claim() -> None:
    """반례 1 — R05 SCATTER_GATHER VERIFIED + 유형 CYCLE: Y2 없음, G-CYCLE-PATH·Y3 나옴, 편집자 Y2 는 거부."""
    facts = facts_for(0, 0, 0, "sg_verified", "CYCLE")
    assert facts is not None and facts.paths is not None and facts.paths.status is PathStatus.VERIFIED
    ids = _ids(facts)
    assert "Y2" not in ids and {"G-CYCLE-PATH", "Y3", "Y1"} <= ids
    masked = masking.mask_for_llm(facts)
    c = candidates(masked, derive_flags(masked))
    plan = default_plan(c)
    plan[SectionV2.OPINION] = [*plan[SectionV2.OPINION][:2], Pick("Y2")]
    assert "unknown_item" in validate_plan(plan, c)


def test_internal_inflow_blocks_outbound_only_claim() -> None:
    """반례 2 — 내부 입금 1 + 외부 출금 1 + 계좌 목적: G-PURPOSE-OUT 없음, "출금만" 없음."""
    facts = facts_for(0, 1, 1, "none", "FAN_OUT")
    assert facts is not None and (facts.inbound.count, facts.internal.count, facts.outbound.count) == (
        0,
        1,
        1,
    )
    assert "G-PURPOSE-OUT" not in _ids(facts) and "O2" not in _ids(facts)
    masked = masking.mask_for_llm(facts)
    c = candidates(masked, derive_flags(masked))
    text = " ".join(
        s.text
        for s in assemble(build_slots(masked, LABELS), default_plan(c), c, render_context(masked, LABELS))
    )
    assert "출금만" not in text and "입금은 없고" not in text


@pytest.mark.parametrize(
    ("obs", "marked"), [("first_only", "b"), ("zero_and_null", "b"), ("second_only", "a")]
)
def test_partial_baseline_marks_only_that_observation(obs: str, marked: str) -> None:
    """반례 — baseline [2.0, null]·[0.0, null]·[null, 2.0]: 섹션 끝 부재 문장 없음, null 쪽 관측값 문장에만."""
    facts = facts_for(1, 0, 0, "none", "FAN_IN", obs=obs)
    assert facts is not None
    masked = masking.mask_for_llm(facts)
    slots = build_slots(masked, LABELS)
    grounds = [s for s in slots[SectionV2.GROUNDS] if s.cites and s.cites[0].startswith("observations.")]
    flagged = [s.cites[0].removeprefix("observations.") for s in grounds if "기준값은 자료 없음" in s.text]
    assert flagged == [marked]
    assert not any(s.text == "비교 기준값은 자료 없음." for s in slots[SectionV2.GROUNDS])
    c = candidates(masked, derive_flags(masked))
    sections = assemble(slots, default_plan(c), c, render_context(masked, LABELS))
    assert failures(facts, sections) == []


@pytest.mark.parametrize("internal", ["small", "other"])
def test_flow_aggregates_carry_scope_when_internal_differs(internal: str) -> None:
    """반례 — 외부 입금 100 USD + 내부 1 USD(또는 다른 통화·결제 방식): 금액 범위·통화·결제 방식 문장에 범위 구절."""
    facts = facts_for(1, 0, 1, "none", "FAN_IN", internal=internal)
    assert facts is not None and facts.internal.count == 1
    masked = masking.mask_for_llm(facts)
    c = candidates(masked, derive_flags(masked))
    sections = assemble(build_slots(masked, LABELS), default_plan(c), c, render_context(masked, LABELS))
    text = " ".join(s.text for s in sections)
    assert "내부 거래를 뺀 입금·출금의 거래 금액은 최소 100.00 미국 달러, 최대 100.00 미국 달러임." in text
    assert "내부 거래를 뺀 입금·출금의 거래 통화는 미국 달러(USD)임." in text
    assert "유로" not in text and "전신환" not in text
    assert failures(facts, sections) == []
