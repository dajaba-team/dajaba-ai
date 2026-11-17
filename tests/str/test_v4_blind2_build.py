"""SCRUM-265 (1/2) — 재블라인드 배포물 (docs/str/08 "재블라인드" 응답 양식·안내문). LLM·DB 0.

사건 파일 11건 + 파일의 대조쌍 1 = 12쌍 · 쌍마다 ④ 문항 · 안내문 228 혼동 두 줄 · 공개물에 버전·회귀 단서 없음.
"""

from __future__ import annotations

import json

from aml_ai.shared.schemas.str import NarrativeSection, SectionV2
from tests.str.v4_blind2_build import BLIND2_INTRO, SUPPORT_QUESTION, blind2_cases, build_blind2
from tests.str.v4_blind2_cases import case_facts, load_cases
from tests.str.v4_blind2_io import diag_hash, responses_template2
from tests.str.v4_blind_support import CaseDrafts

DOC = load_cases()
RUN = "20261117-000000"


def _sections(tag: str) -> list[NarrativeSection]:
    return [NarrativeSection(section=s, text=f"{tag} {s.value} 문장임.") for s in SectionV2]


def _drafts() -> list[CaseDrafts]:
    return [CaseDrafts(c, _sections("가"), _sections("가"), _sections("나")) for c in blind2_cases(DOC)]


def test_blind2_cases_follow_file() -> None:
    cases = blind2_cases(DOC)
    facts = case_facts(DOC)
    assert [c.case_id for c in cases] == [c["case_id"] for c in DOC["cases"]]
    assert all(c.facts == facts[c.case_id] for c in cases)
    judged = {c["case_id"] for c in DOC["cases"] if c["role"] == "judged"}
    assert all(c.group is None for c in cases if c.case_id in judged)  # 새 8건은 묶음 표시 없음


def test_twelve_pairs_with_control_from_file() -> None:
    out = build_blind2(_drafts(), DOC, seed=7, run_id=RUN)
    pairs = out.key["pairs"]
    assert len(pairs) == len(out.public["pairs"]) == len(out.diag["pairs"]) == 12
    controls = [p for p in pairs if p["control"]]
    assert len(controls) == 1 and controls[0]["case_id"] == DOC["control_case_id"]
    assert controls[0]["A"] == controls[0]["B"] == "v4"
    assert out.md.count(SUPPORT_QUESTION) == 12
    assert build_blind2(_drafts(), DOC, seed=7, run_id=RUN) == out  # 같은 시드 → 같은 배포물


def test_intro_explains_fix_count_sides_and_choice_values() -> None:
    out = build_blind2(_drafts(), DOC, seed=7, run_id=RUN)
    assert out.md.startswith(BLIND2_INTRO)
    for want in ("고쳐야 할 문장만", "없으면 0", "fix_a 는 A 초안", "fix_b 는 B 초안", "예:", "same"):
        assert want in BLIND2_INTRO, want
    assert "support_a" in BLIND2_INTRO and "yes/no/unknown" in BLIND2_INTRO


def test_public_has_no_version_or_role_hints() -> None:
    out = build_blind2(_drafts(), DOC, seed=7, run_id=RUN)
    public = out.md + json.dumps(out.public, ensure_ascii=False)
    for word in ("v2", "v4", "narrative_", "control", "대조", "regression", "회귀", "seed", "supported", "mix_",
                 "uns_", "sup_", "reg_"):  # fmt: skip
        assert word not in public, word


def test_run_id_binds_public_diag_key_and_template() -> None:
    out = build_blind2(_drafts(), DOC, seed=7, run_id=RUN)
    assert out.public["run_id"] == out.diag["run_id"] == out.key["run_id"] == RUN
    assert out.key["diag_sha256"] == diag_hash(out.diag)
    assert {row["run_id"] for row in responses_template2(out.public)} == {RUN}
