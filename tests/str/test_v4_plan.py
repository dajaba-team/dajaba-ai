"""SCRUM-228 — 순서 목록(Plan) 기본값·검증·폴백 + 모든 변형 조합 코드 검사 (docs/str/08 narrative_v4 3·5번).

편집자(LLM)는 아직 없음 — 가짜 Plan → validate_plan → 조립 / 실패면 default_plan 으로 완성.
"""

from __future__ import annotations

import itertools

import pytest

from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.str.domain import masking
from aml_ai.str.domain.catalog_types import render_context
from aml_ai.str.domain.constants_v4 import CONNECTIVES
from aml_ai.str.domain.derived_flags import derive_flags
from aml_ai.str.domain.display_slots import build_slots
from aml_ai.str.domain.narrative_assembly import assemble
from aml_ai.str.domain.narrative_plan import Pick, candidates, default_plan, validate_plan
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.narrative_v4_builder import build_v4
from tests.str.v4_slot_support import facts_sources, failures, load_fixture

LABELS = load_display_labels()
FACTS = load_fixture("facts_fan_in.json")
MASKED = masking.mask_for_llm(FACTS)
CANDS = candidates(MASKED, derive_flags(MASKED))
DEFAULT = default_plan(CANDS)


def test_default_plan_shape() -> None:
    assert [p.item_id for p in DEFAULT[SectionV2.GROUNDS]] == ["G-PURPOSE-IN", "G-COUNTERPARTY", "G-PRIOR"]
    assert [p.item_id for p in DEFAULT[SectionV2.OPINION]] == ["O-HEAD-FAN_IN", "C1", "F1", "F2"]
    assert all(p.variant_id == 0 and p.connective_id == "none" for ps in DEFAULT.values() for p in ps)
    assert validate_plan(DEFAULT, CANDS) == []


def _plan(grounds: list[Pick], opinion: list[Pick]) -> dict:
    return {SectionV2.GROUNDS: grounds, SectionV2.OPINION: opinion}


HEAD, C1 = Pick("O-HEAD-FAN_IN"), Pick("C1")


@pytest.mark.parametrize(
    ("plan", "reason"),
    [
        (_plan([Pick("G-CYCLE-PATH")], [HEAD, C1]), "unknown_item"),  # 후보 밖(조건 거짓)
        (_plan([Pick("G-PRIOR", variant_id=9)], [HEAD, C1]), "unknown_variant"),
        (
            _plan([Pick("G-PRIOR"), Pick("G-COUNTERPARTY", connective_id="therefore")], [HEAD, C1]),
            "unknown_connective",
        ),
        (_plan([Pick("G-PRIOR", connective_id="also")], [HEAD, C1]), "connective_on_first"),
        (_plan([Pick("G-PRIOR"), Pick("G-PRIOR")], [HEAD, C1]), "duplicate_item"),
        (_plan([], [C1, HEAD]), "head_not_first"),
        (_plan([], [HEAD]), "required_missing"),
        (_plan([], [HEAD, C1, Pick("F1"), Pick("F2"), Pick("F3")]), "too_many_optional"),
        (_plan([Pick("C1")], [HEAD, C1]), "unknown_item"),  # 확인 사항을 GROUNDS 에
        ({**_plan([], [HEAD, C1]), SectionV2.METHOD: [Pick("G-PRIOR")]}, "section_not_allowed"),
    ],
)
def test_validate_plan_reasons(plan: dict, reason: str) -> None:
    assert reason in validate_plan(plan, CANDS)


def test_bad_editor_plan_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """편집자 Plan 이 틀리면 코드 Plan 으로 완성 — 로그에 사유 코드만(본문 없음)."""
    from aml_ai.str.infrastructure import narrative_v4_builder

    calls: list[tuple] = []
    monkeypatch.setattr(narrative_v4_builder.log, "warning", lambda *a, **kw: calls.append((a, kw)))
    out = build_v4(MASKED, LABELS, editor_plan=_plan([Pick("G-NOPE")], [HEAD]))
    assert out == build_v4(MASKED, LABELS)
    assert calls[0][0] == ("narrative_v4_plan_rejected",)
    assert calls[0][1]["extra"]["reasons"] == ["unknown_item", "required_missing"]


def test_valid_editor_plan_is_used() -> None:
    plan = _plan([Pick("G-PRIOR", 1)], [Pick("O-HEAD-FAN_IN", 1), Pick("C1", 1, "also"), Pick("F3")])
    assert validate_plan(plan, CANDS) == []
    opinion = next(s for s in build_v4(MASKED, LABELS, editor_plan=plan) if s.section is SectionV2.OPINION)
    assert opinion.text.startswith("위 입금은 자금 집중 유형으로 분류되어")
    assert "또한 " in opinion.text


@pytest.mark.parametrize(("source", "facts"), facts_sources(), ids=[s for s, _ in facts_sources()])
def test_every_variant_and_connective_combination_passes_code_checks(source: str, facts) -> None:  # type: ignore[no-untyped-def]
    """후보 전부 × 변형 전부 × 연결어 전부 — 조립 결과 코드 검사 실패 0(변형은 사실 범위가 같다)."""
    masked = masking.mask_for_llm(facts)
    flags = derive_flags(masked)
    cands = candidates(masked, flags)
    slots, ctx = build_slots(masked, LABELS, flags), render_context(masked, LABELS)
    max_v = max(len(i.variants) for i in cands.by_id.values())
    for v, conn in itertools.product(range(max_v), CONNECTIVES):
        plan = {
            SectionV2.GROUNDS: [
                Pick(i.id, min(v, len(i.variants) - 1), conn if n else "none")
                for n, i in enumerate(cands.grounds)
            ],
            SectionV2.OPINION: [Pick(cands.head.id, min(v, 1))]
            + [Pick(i.id, min(v, len(i.variants) - 1), conn) for i in cands.checks],
        }
        sections = assemble(slots, plan, cands, ctx)
        assert failures(facts, sections) == [], (source, v, conn)
