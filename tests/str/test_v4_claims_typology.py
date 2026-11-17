"""SCRUM-265 (2/2) — 주장 조합 검사 규칙 추가 (docs/str/08 "유형 뒷받침 판정·문구"). LLM·DB 0.

조합 = 기존 `COMBOS` + 판정 경계 조합(`TYPOLOGY_COMBOS`). 기본 Plan + 편집자 Plan(검증 통과분) 전부에서
① 뒷받침 안 됨이면 금지 낱말 0(GROUNDS·OPINION, 낱말 단위) ② 판정이 있으면 GROUNDS 첫 문장 = 판정 문장,
뒷받침 안 됨이면 OPINION 둘째 = C0. ③ 통화 종류(등록 + 미등록) 둘 이상인데 범위 없는 "거래 금액은 모두" 없음(추가 검토 1·2차)
④ 미등록 통화가 있으면 INSTRUMENT 통화 열거와 METHOD 합계 문장에 "대응이 확인된 통화"(추가 검토 2차).
새 조합은 06 코드 검사 실패 0 도.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import Facts
from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import masking
from aml_ai.str.domain.catalog_types import render_context
from aml_ai.str.domain.derived_flags import derive_flags
from aml_ai.str.domain.display_slots import build_slots
from aml_ai.str.domain.narrative_assembly import assemble
from aml_ai.str.domain.narrative_plan import candidates, default_plan
from aml_ai.str.domain.typology_support import Support, typology_support
from aml_ai.str.domain.typology_support_text import support_sentence
from tests.str.v4_claims_support import COMBOS, LABELS, editor_plans
from tests.str.v4_claims_typology import TYPOLOGY_COMBOS
from tests.str.v4_slot_support import failures
from tests.str.v4_typology_words import banned_hits

ALL = COMBOS + TYPOLOGY_COMBOS


def test_typology_combos_cover_every_judgment() -> None:
    seen = {
        (f.typology.value if f.typology else None, typology_support(masking.mask_for_llm(f))) for _, f in ALL
    }
    for typology in ("FAN_IN", "FAN_OUT"):
        assert {(typology, s) for s in Support} <= seen, typology
    assert {("CYCLE", Support.SUPPORTED), ("CYCLE", Support.UNCONFIRMED)} <= seen
    assert {("SCATTER_GATHER", Support.SUPPORTED), ("SCATTER_GATHER", Support.UNCONFIRMED)} <= seen
    assert len(ALL) > len(COMBOS)
    assert any(len(f.amount_range) >= 2 and any(r.min == r.max for r in f.amount_range) for _, f in ALL)
    assert any(len(f.amount_range) == 1 and f.unmapped_currencies for _, f in ALL)  # 등록 1 + 미등록 1


@pytest.mark.parametrize(("args", "facts"), ALL, ids=[str(a) for a, _ in ALL])
def test_judgment_rules_hold(args: tuple, facts: Facts) -> None:
    masked = masking.mask_for_llm(facts)
    flags = derive_flags(masked)
    c = candidates(masked, flags)
    slots, ctx = build_slots(masked, LABELS, flags), render_context(masked, LABELS)
    support = typology_support(masked)
    sentence = support_sentence(masked, LABELS)
    assert (sentence is None) == (support is None), args
    kinds = len(masked.get("amount_range", [])) + len(masked.get("unmapped_currencies", []))
    multi = kinds >= 2  # 통화 종류 = 등록 + 미등록(추가 검토 2차)
    for plan in editor_plans(c):
        by = {s.section: s.text for s in assemble(slots, plan, c, ctx)}
        assert not (multi and "입금·출금의 거래 금액은 모두" in by[SectionV2.METHOD]), args
        if masked.get("unmapped_currencies"):
            assert (
                "거래 통화 가운데 대응이 확인된 통화는" in by[SectionV2.INSTRUMENT]
                or not masked["amount_range"]
            ), args
            for flow, word in (("inbound", "입금"), ("outbound", "출금")):
                rows = masked[flow]["by_currency"]
                if rows and masked[flow]["count"] > sum(c["count"] for c in rows):  # 그 방향에 미등록 있음
                    assert f"{word} 가운데 대응이 확인된 통화 거래의 합계는" in by[SectionV2.METHOD], args
        if support is None:
            continue
        assert by[SectionV2.GROUNDS].startswith(sentence.text), args  # type: ignore[union-attr]
        if support is not Support.SUPPORTED:
            assert banned_hits(by[SectionV2.GROUNDS] + " " + by[SectionV2.OPINION]) == [], args
            assert plan[SectionV2.OPINION][1].item_id == "C0", args


@pytest.mark.parametrize(("args", "facts"), TYPOLOGY_COMBOS, ids=[str(a) for a, _ in TYPOLOGY_COMBOS])
def test_typology_combos_pass_code_checks(args: tuple, facts: Facts) -> None:
    masked = masking.mask_for_llm(facts)
    flags = derive_flags(masked)
    c = candidates(masked, flags)
    sections = assemble(
        build_slots(masked, LABELS, flags), default_plan(c), c, render_context(masked, LABELS)
    )
    assert [(f.check, f.section, f.reason) for f in failures(facts, sections)] == [], args
