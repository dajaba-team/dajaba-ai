"""SCRUM-228 — 슬롯 정상·변조 표 (docs/str/08 narrative_v4 2번, 지시서 4절 완료 기준).

정상: 픽스처 6개 + v4 few-shot facts 3개 → 조립 결과 코드 검사 UNPARSED·MISMATCH 0.
변조: 슬롯 문장 숫자 덩이 ±1 → 그 섹션 match=false. 조용한 통과는 06 검사기의 포함 판정 넷 뿐이어야 한다
(`Mutation.known_limit` — 문형으로 못 막는 설계, ★C 보고). 그 밖의 조용한 통과는 0.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str.narrative import NARRATIVE_TEXT_MAX
from aml_ai.str.domain import masking
from aml_ai.str.domain.catalog_types import render_context
from aml_ai.str.domain.derived_flags import derive_flags
from aml_ai.str.domain.display_slots import build_slots
from aml_ai.str.domain.narrative_assembly import section_lengths
from aml_ai.str.domain.narrative_plan import candidates, default_plan
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.v4_claims_support import facts_for
from tests.str.v4_mutation_support import mutations
from tests.str.v4_slot_support import assembled, facts_sources, failures, longest_case

_OBS_AXIS = ("first_only", "zero_and_null", "half_window")  # 관측값 둘·baseline 일부·관측 구간 한쪽
SOURCES = [
    *facts_sources(),
    ("longest_case", longest_case()),
    *((f"obs_{o}", facts_for(1, 0, 0, "none", "FAN_IN", obs=o)) for o in _OBS_AXIS),
]  # 마지막은 paths VERIFIED·통화 3개


def test_sources_include_fixtures_fewshot_and_multi_currency() -> None:
    names = [s for s, _ in SOURCES]
    assert len(names) == 15 and "facts_multi_currency.json" in names
    assert sum(n.startswith("fewshot/") for n in names) == 5


@pytest.mark.parametrize(("source", "facts"), SOURCES, ids=[s for s, _ in SOURCES])
def test_normal_slots_pass_every_code_check(source: str, facts) -> None:  # type: ignore[no-untyped-def]
    assert [(f.check, f.section, f.reason) for f in failures(facts, assembled(facts))] == []


@pytest.mark.parametrize(("source", "facts"), SOURCES, ids=[s for s, _ in SOURCES])
def test_mutations_never_pass_silently_outside_known_limits(source: str, facts) -> None:  # type: ignore[no-untyped-def]
    muts = mutations(source, facts)
    assert muts, source
    silent = [m for m in muts if not m.caught_by and not m.known_limit]
    assert silent == []


def test_subject_place_instrument_mutations_all_caught() -> None:
    """포함 판정이 없는 문형(경보·상대·자행/타행·결제·계좌·개설일)은 변조가 전부 잡힌다 — 상대 수가 경로 계좌 수와 같아지는 경우만 예외."""
    for source, facts in SOURCES:
        for m in mutations(source, facts):
            if m.section in ("SUBJECT", "PLACE", "INSTRUMENT") and not m.path_accounts_hit:
                assert m.caught_by, (source, m.sentence, m.original, m.mutated)


def test_longest_case_fits_section_limit() -> None:
    """통화 3개 + 미등록 1개 + paths VERIFIED — 슬롯 + 카탈로그 섹션 최대 글자 수 < 1,200(PR 표)."""
    facts = longest_case()
    masked = masking.mask_for_llm(facts)
    flags = derive_flags(masked)
    labels = load_display_labels()
    cands = candidates(masked, flags)
    lengths = section_lengths(
        build_slots(masked, labels, flags), default_plan(cands), cands, render_context(masked, labels)
    )
    assert max(lengths.values()) < NARRATIVE_TEXT_MAX
    assert failures(facts, assembled(facts)) == []
