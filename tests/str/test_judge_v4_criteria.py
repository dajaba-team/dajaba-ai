"""SCRUM-268 — judge_v4 사전 기준 1·2 사례 (docs/str/08 "judge_v4 사전 기준 측정", 09 SCRUM-268). LLM·DB 0.

기준 1: 평가자마다 자기 기준 본문(judge_v3 = v2 facts_fan_in, judge_v4 = v4 demo_7)에 주입 7·8·10·11, 11 은 단독 호출,
참고 12·23. 기준 2: v4 18건 판정 문장 text 만 블록과 반대로(다른 문장·cites diff 0), 코드 검사 통과 표.
dry-run 호출 0·sha256 결정적 · 재블라인드 키·진단·응답 접근 없음.
"""

from __future__ import annotations

import builtins
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from aml_ai.str.domain import masking
from aml_ai.str.domain.typology_support import Support, typology_support
from aml_ai.str.domain.typology_support_text import support_sentence
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.str.injection_live_support import EXPECTS, base_facts, base_narrative
from tests.str.judge_stability_v4 import build_cases, code_check_failures
from tests.str.judge_v4_criteria import C1_INJECTIONS, build_criteria_cases, dry_run, flip_narrative
from tests.str.v4_blind2_cases import case_facts, load_cases

BLIND2 = case_facts(load_cases())
DEMO = [("demo_7", BLIND2["sup_fan_in"]), ("demo_48", BLIND2["uns_fan_in"])]  # DB 대신 가짜 facts
BLIND_PRIVATE = ("v4_blind_key_", "v4_blind_diag_", "v4_blind_responses_")


@pytest.fixture(scope="module")
def cases() -> list[Any]:
    return build_criteria_cases(DEMO)


def test_case_list(cases: list[Any]) -> None:
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids)) == 6 + 7 + 18 + 18  # 추가 검토 2차 — 기준 2 대조 18
    assert C1_INJECTIONS == (7, 8, 10, 11)
    c1 = {c.case_id for c in cases if c.criterion == 1}
    assert c1 == {f"c1:{p}:{r}" for p in ("judge_v3", "judge_v4") for r in ("base", "inject_7", "inject_8",
                  "inject_10", "inject_11", "ref_23")} | {"c1:judge_v4:ref_12"}  # fmt: skip
    assert Counter((c.criterion, c.prompt) for c in cases) == {(1, "judge_v3"): 6, (1, "judge_v4"): 7,
                                                               (2, "judge_v4"): 36}  # fmt: skip
    assert Counter(c.role for c in cases if c.criterion == 2) == {"flip": 18, "control": 18}


def test_controls_are_unflipped_originals_paired_with_flips(cases: list[Any]) -> None:
    """대조 = 뒤집지 않은 원래 v4 초안(254 사건 그대로) · 뒤집기와 짝(같은 사건 id) · judge_v4."""
    originals = {c.case_id: c for c in build_cases(DEMO) if c.kind == "v4"}
    controls = {c.case_id: c for c in cases if c.role == "control"}
    flips = {c.case_id for c in cases if c.role == "flip"}
    assert set(controls) == {f"c2ctl:{k}" for k in originals} and flips == {f"c2:{k}" for k in originals}
    for k, orig in originals.items():
        ctl = controls[f"c2ctl:{k}"]
        assert ctl.prompt == "judge_v4" and ctl.facts == orig.facts and ctl.narrative == orig.narrative


def test_each_judge_gets_its_own_base(cases: list[Any]) -> None:
    by_id = {c.case_id: c for c in cases}
    v3, v4 = by_id["c1:judge_v3:base"], by_id["c1:judge_v4:base"]
    assert v3.facts == base_facts() and v3.narrative == base_narrative()  # 주입 12 와 같은 v2 본문
    demo7 = next(c for c in build_cases(DEMO) if c.case_id == "demo_7")
    assert v4.facts == demo7.facts and v4.narrative == demo7.narrative
    for p, base in (("judge_v3", v3), ("judge_v4", v4)):
        for k in C1_INJECTIONS:
            inj = by_id[f"c1:{p}:inject_{k}"]
            assert inj.facts == base.facts and inj.narrative != base.narrative
            assert inj.target == EXPECTS[k]["target"] and inj.role == "inject"


def test_only_injection_11_is_judge_only(cases: list[Any]) -> None:
    """11 은 verify 경로면 OPINION_PRESENT 로 CODE_FAILED — 평가자 단독 호출(127 측정과 같음)."""
    for c in cases:
        assert c.judge_only is c.case_id.endswith(":inject_11"), c.case_id
        failures = code_check_failures(c)
        assert (failures > 0) is c.judge_only, (c.case_id, failures)


def _flipped_sentence(case: Any) -> tuple[str, str]:
    """(원래 판정 문장, 그 자리에 들어간 문장) — 판정 문장 앞뒤 글자는 그대로인지도 확인."""
    original = support_sentence(masking.mask_for_llm(case.facts), load_display_labels()).text  # type: ignore[union-attr]
    changed = [(a, b) for a, b in zip(case.narrative, flip_narrative(case), strict=True) if a != b]
    assert len(changed) == 1 and changed[0][0].section.value == "GROUNDS", case.case_id
    before, after = changed[0]
    assert (before.cites, before.evidence_ids) == (after.cites, after.evidence_ids), case.case_id
    assert before.text.count(original) == 1, case.case_id
    prefix, suffix = before.text.split(original)
    assert after.text.startswith(prefix) and after.text.endswith(suffix), case.case_id
    return original, after.text[len(prefix) : len(after.text) - len(suffix)]


def test_flip_changes_only_the_judgement_sentence_against_block() -> None:
    v4 = [c for c in build_cases(DEMO) if c.kind == "v4"]
    assert len(v4) == 18
    for c in v4:
        original, flipped = _flipped_sentence(c)
        assert flipped != original and flipped.endswith("."), c.case_id
        if typology_support(masking.mask_for_llm(c.facts)) is Support.SUPPORTED:
            assert ("미치지 않음" in flipped or "확인되지 않음" in flipped) and "충족" not in flipped, (
                c.case_id
            )
        else:
            assert flipped.endswith(("탐지 기준을 충족함.", "분류와 부합함.")), c.case_id


def test_all_flips_pass_code_checks(cases: list[Any]) -> None:
    """11/18 확인: 뒤집기 18/18 · 대조 18/18 통과 — 기준 2 는 평가자 단계만 잼(못 넘으면 판정 불가)."""
    for role in ("flip", "control"):
        picked = [c for c in cases if c.role == role]
        assert [code_check_failures(c) for c in picked] == [0] * 18, role


def test_dry_run_no_call_and_deterministic(cases: list[Any]) -> None:
    first, second = dry_run(cases), dry_run(cases)
    assert first == second and len(first) == 49
    assert set(first[0]) == {"case_id", "criterion", "prompt", "role", "user_sha256", "code_check_failures"}
    assert {r["prompt"] for r in first} == {"judge_v3", "judge_v4"}


def test_blind_private_files_never_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    real_open, real_read = builtins.open, Path.read_text

    def spy_open(file: Any, *a: Any, **kw: Any) -> Any:
        opened.append(str(file))
        return real_open(file, *a, **kw)

    def spy_read(self: Path, *a: Any, **kw: Any) -> str:
        opened.append(str(self))
        return real_read(self, *a, **kw)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(Path, "read_text", spy_read)
    dry_run(build_criteria_cases(DEMO))
    assert opened and not [p for p in opened if any(m in p for m in BLIND_PRIVATE)]
