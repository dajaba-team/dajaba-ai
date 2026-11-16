"""SCRUM-228 (2/2) 1단계 — 블라인드 하네스 공용 함수 (docs/str/08 "narrative_v4 블라인드 비교 하네스"). LLM·DB 0.

사건 8 · 공개물에 버전 단서 없음 · 키 없이는 매핑 불가 · 대조쌍 표시는 키에만.
"""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.schemas.str import NarrativeSection, SectionV2
from aml_ai.str.domain import masking
from aml_ai.str.domain.fact_keys import attach_evidence
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.narrative_v4_builder import build_v4
from tests.str.v4_blind_support import BlindCase, CaseDrafts, blind_cases, build_blind, unify_notation
from tests.str.v4_slot_support import failures, load_fixture

LABELS = load_display_labels()


def test_blind_cases_are_eight_with_required_shapes() -> None:
    cases = blind_cases()
    ids = [c.case_id for c in cases]
    assert len(cases) == 8 and len(set(ids)) == 8
    assert {"fan_in", "fan_in_b", "fan_out", "cycle_nopaths", "scatter_gather"} <= set(ids)
    built = [
        c.facts
        for c in cases
        if c.case_id not in {"fan_in", "fan_in_b", "fan_out", "cycle_nopaths", "scatter_gather"}
    ]
    assert any(f.internal.count > 0 for f in built)
    assert any(
        f.observations
        and any(o.baseline is None for o in f.observations)
        and any(o.baseline is not None for o in f.observations)
        for f in built
    )  # noqa: E501
    assert any(f.customer is None for f in built)
    partial = next(c.facts for c in cases if c.case_id == "partial_baseline")
    names = [o.name for o in partial.observations]
    assert names == ["distinct_senders_24h", "inflow_outflow_ratio_2h"]  # 한 글자 이름 없음
    assert list(partial.model_signals) == names
    bases = [o.basis for o in partial.observations]
    assert bases == ["distinct_inbound_counterparties", "inflow_minus_outflow"]
    shown = [LABELS["observation_basis"][b] for b in bases]
    assert len(set(shown)) == 2  # 같은 표기 두 번("…는 3개임. …는 4개임.") 없음
    assert [o.unit for o in partial.observations] == ["count", "ratio"]
    assert partial.observations[0].value == partial.inbound.count == 1  # 입금 1건 → 서로 다른 송금인 1
    diff = sum(float(t.total) for t in partial.inbound.by_currency) - sum(
        float(t.total) for t in partial.outbound.by_currency
    )
    assert partial.observations[1].value == diff == 0.0  # 표기 "유입액에서 유출액을 뺀 값"과 맞게
    assert [o.baseline is None for o in partial.observations] == [False, True]  # baseline 일부 null 유지
    assert failures(partial, _v4(partial)) == []  # 이 사건 v4 조립 결과 코드 검사 실패 0
    assert {c.group for c in cases} == {"g1", "g2"}  # 묶음은 번호 — 좌우 초안 A·B 와 안 헷갈리게
    assert not {c.group for c in cases} & {"A", "B"}


def _v4(facts) -> list[NarrativeSection]:  # type: ignore[no-untyped-def]
    return attach_evidence(build_v4(masking.mask_for_llm(facts), LABELS), facts)


def _v2(case_id: str) -> list[NarrativeSection]:
    return [NarrativeSection(section=s, text=f"{case_id} 원본 {s.value} USD 문장.") for s in SectionV2]


def _drafts() -> list[CaseDrafts]:
    out = []
    for name in ("fan_in", "fan_out", "cycle_nopaths"):
        facts = load_fixture(f"facts_{name}.json")
        v2 = _v2(name)
        unified = [s.model_copy(update={"text": unify_notation(s.text, LABELS, facts).text}) for s in v2]
        out.append(
            CaseDrafts(
                BlindCase(name, "g1" if name != "cycle_nopaths" else None, facts), v2, unified, _v4(facts)
            )
        )
    return out


FORBIDDEN = (
    "prompt_version",
    "generation_meta",
    "llm_model",
    "tokens",
    "narrative_",
    "v2",
    "v4",
    "대조",
    "control",
)


@pytest.mark.parametrize("seed", [0, 1, 7, 12345])
def test_public_outputs_carry_no_version_clue(seed: int) -> None:
    out = build_blind(_drafts(), seed)
    public = json.dumps(out.public, ensure_ascii=False)
    for word in FORBIDDEN:
        assert word not in out.md and word not in public, word
    assert "seed" not in out.md and "seed" not in public
    if seed >= 1000:  # 짧은 시드는 쌍 번호와 겹쳐 부분문자열로 못 봄
        assert str(seed) not in public and str(seed) not in out.md


def test_public_carries_no_metrics_only_pair_numbers() -> None:
    """공개물(md·json)만으로 A/B 의 코드 검사·길이를 알 수 없음 — 지표는 진단 파일에만."""
    out = build_blind(_drafts(), 4)
    assert all(set(p) == {"pair_no", "group"} for p in out.public["pairs"])
    for word in ("code_check", "chars", "sentences", "글자 수", "문장 수:", "코드 검사"):
        assert word not in out.md and word not in json.dumps(out.public, ensure_ascii=False), word
    assert {p["pair_no"] for p in out.diag["pairs"]} == {p["pair_no"] for p in out.public["pairs"]}


def test_pairs_are_cases_plus_one_control_and_deterministic() -> None:
    drafts = _drafts()
    out = build_blind(drafts, 3)
    assert len(out.public["pairs"]) == len(drafts) + 1 == len(out.key["pairs"])
    for n in range(1, len(drafts) + 2):
        assert f"쌍 {n}" in out.md
    assert build_blind(drafts, 3) == out


def test_group_shown_as_numbered_bundle_not_letter() -> None:
    md = build_blind(_drafts(), 6).md
    assert "같은 고객 묶음 1" in md
    assert "묶음 g1" not in md and "묶음 A" not in md and "묶음 B" not in md


def test_side_shape_is_identical_for_a_and_b() -> None:
    for pair in build_blind(_drafts(), 5).diag["pairs"]:
        assert set(pair["A"]) == set(pair["B"]) == {"code_check_failures", "chars", "sentences"}


def test_mapping_needs_key_sides_vary_with_seed() -> None:
    """좌우는 시드로 바뀌고(같은 사건이 A 쪽 v4 인 때·B 쪽 v4 인 때 둘 다 있음) 공개물엔 시드가 없음."""
    sides = set()
    for seed in range(30):
        key = build_blind(_drafts(), seed).key
        sides |= {(p["case_id"], p["A"]) for p in key["pairs"] if not p["control"]}
    assert ("fan_in", "v2") in sides and ("fan_in", "v4") in sides


def test_v2_original_only_in_key_and_unified_shown() -> None:
    out = build_blind(_drafts(), 2)
    assert "원본 SUBJECT USD 문장" not in out.md  # 통일 전 원본은 키에만
    assert "미국 달러(USD)" in out.md
    assert out.key["v2_original"]["fan_in"][0]["text"].endswith("USD 문장.")


def test_control_pair_marked_only_in_key() -> None:
    drafts = _drafts()
    out = build_blind(drafts, 9)
    controls = [p for p in out.key["pairs"] if p["control"]]
    assert len(controls) == 1 and controls[0]["A"] == controls[0]["B"] == "v4"
    v4_text = next(d for d in drafts if d.case.case_id == controls[0]["case_id"]).v4[0].text
    assert out.md.count(v4_text) >= 3  # 원래 쌍 1 + 대조쌍 양쪽
    pub = next(p for p in out.public["pairs"] if p["pair_no"] == controls[0]["pair_no"])
    assert set(pub) == set(out.public["pairs"][0])  # 다른 쌍과 같은 모양
    diag = next(p for p in out.diag["pairs"] if p["pair_no"] == controls[0]["pair_no"])
    assert diag["A"] == diag["B"]  # 같은 초안 두 개
