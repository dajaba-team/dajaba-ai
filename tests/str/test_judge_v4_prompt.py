"""SCRUM-268 — judge_v4 프롬프트·평가자 입력 (docs/str/05 "judge_v4", 06 "judge_v4"). LLM·DB 0.

judge_v4 user = judge_v3 user + 블록뿐(고정 비교) · system 은 정한 네 줄만 다름 · 스키마·동결 등록 ·
judge_v3 평가자 입력 sha256 = develop(회귀 0, 254 사건 19 — 시연 후보 2건은 가짜 facts).
"""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path

import pytest

from aml_ai.shared.schemas.str import JudgeOutV2
from aml_ai.shared.schemas.str.narrative_version import llm_output_model
from aml_ai.str.domain.frozen_prompts import FROZEN_PROMPTS
from aml_ai.str.domain.typology_support_block import render_support_block
from aml_ai.str.infrastructure.judge import render_judge_user
from aml_ai.str.infrastructure.narrative_generator import load_prompt
from tests.str.judge_stability_v4 import V4Case, build_cases, verify_inputs
from tests.str.v4_blind2_cases import case_facts, load_cases

PROMPTS = Path(__file__).resolve().parents[2] / "src/aml_ai/str/prompts"
BLIND2 = case_facts(load_cases())
DEMO = [("demo_7", BLIND2["sup_fan_in"]), ("demo_48", BLIND2["uns_fan_in"])]  # DB 대신 가짜 facts
BLOCK_HEADER = "TYPOLOGY_SUPPORT (코드가 FACTS 에서 계산한 유형 뒷받침 판정):"

# develop(608c084)에서 judge_v3 로 만든 평가자 user sha256 — 블록 추가 뒤에도 같아야 함.
# SCRUM-269(v4-catalog-2): v4 본문이 바뀐 17건만 새 값(템플릿·렌더 그대로) — customer_missing·injection:23 은 608c084 값 그대로
# SCRUM-269 2/2(v4-catalog-3): C0 가 바뀐 10건만 새 값 — CYCLE·뒷받침됨·v2 9건은 v4-catalog-2 값 그대로
V3_USER_SHA256 = {
    "228:fan_in": "6e57c6e7d44a0662e64adc3822a7ade3048ff253fd28d38b726d7f0e77365012",
    "228:fan_in_b": "6e57c6e7d44a0662e64adc3822a7ade3048ff253fd28d38b726d7f0e77365012",
    "228:fan_out": "24d62dcafe390b19e6bfcceb26b0c43bcc98240286eb649cc1e717dfb70ec4ee",
    "228:cycle_nopaths": "2630441e317f3f484251335dfd41c5670b9d47821e6f1467fa71973563c3e493",
    "228:scatter_gather": "27d6650f882770737904523f8d7b82ebfa104528265d551bba656c98f8d7eeeb",
    "228:internal_transfer": "2685ae6e09591a866363d9d6e25fda11304cc808c9cee084f910558c4e24eee1",
    "228:partial_baseline": "dda5e2c6a237f8699ab0db5d6776832ce6647d96205c0ddfef6768dbcaa5b2a2",
    "228:customer_missing": "fe0713340de1e909a27f22f6f5f1d5848781ece790c4272bd717fd870d714634",
    "blind2:sup_fan_in": "b9b9ad1e2a673d0aad0050c49b8504713eeb4b36b73ee03026be7db4138a3f7d",
    "blind2:sup_fan_out": "da9b7dd026fc3eaee7015bf93b998eef3ea695584e7e4be0f04002911899c8b6",
    "blind2:sup_cycle": "901d5f852cda631da9c87913a64f6863c76a28abd0aeba86065e8edde6e1271a",
    "blind2:sup_scatter_gather": "13adf1eebf2e77d3066c6d1a333cc32b91f608b769e0349cab09f664c2235411",
    "blind2:uns_cycle": "4c1762be3b602e41f572af3756dcf12ccbcece24a941e5bc9cc2a0c4e06c5610",
    "blind2:uns_scatter_gather": "804ffc2a9265cb41eb94a076ec4976089d73aa66566d216f7e7ffa8dff373a9c",
    "blind2:uns_fan_in": "b62c309b8374f7fe6840ea842758e20ca6cefa24dd72c47c9258ca3aeaeef910",
    "blind2:mix_fan_in": "cfa5bc21905fda792d1c808e614da081df290bce758208787a32814789c232e8",
    "demo_7": "b9b9ad1e2a673d0aad0050c49b8504713eeb4b36b73ee03026be7db4138a3f7d",
    "demo_48": "b62c309b8374f7fe6840ea842758e20ca6cefa24dd72c47c9258ca3aeaeef910",
    "injection:23": "387277e8d44c48006b0bceb16d57e72e8fea7806f561671681d6ea3bfb415f60",
}


@pytest.fixture(scope="module")
def cases() -> list[V4Case]:
    return build_cases(DEMO)


def _user(prompt: str, case: V4Case) -> str:
    _, template = load_prompt(prompt)
    facts, narrative, keys = verify_inputs(case)
    return render_judge_user(template, facts_masked=facts, narrative=narrative, fact_keys=keys,
                             request_sections=[s.section.value for s in narrative])  # fmt: skip


def _diff(a: list[str], b: list[str]) -> tuple[list[str], list[str]]:
    lines = list(difflib.ndiff(a, b))
    return [x[2:] for x in lines if x.startswith("- ")], [x[2:] for x in lines if x.startswith("+ ")]


def test_v3_user_unchanged_from_develop(cases: list[V4Case]) -> None:
    got = {c.case_id: hashlib.sha256(_user("judge_v3", c).encode("utf-8")).hexdigest() for c in cases}
    assert got == V3_USER_SHA256


def test_v4_user_is_v3_user_plus_block_only(cases: list[V4Case]) -> None:
    """judge_v4 user = judge_v3 user 의 FACT_KEYS 바로 앞에 블록 한 덩이를 끼운 것 — 그 밖 글자 같음."""
    for c in cases:
        v3 = _user("judge_v3", c)
        block = render_support_block(verify_inputs(c)[0])
        assert v3.count("\n\nFACT_KEYS") == 1
        expected = v3.replace("\n\nFACT_KEYS", f"\n\n{BLOCK_HEADER}\n{block}\n\nFACT_KEYS")
        assert _user("judge_v4", c) == expected, c.case_id


def test_v4_user_carries_block_for_every_v4_case(cases: list[V4Case]) -> None:
    for c in cases:
        user = _user("judge_v4", c)
        assert "{{typology_support}}" not in user
        assert '"support": "' in user, c.case_id  # 254 사건은 전부 판정 있는 유형


def test_v4_system_differs_only_in_four_lines() -> None:
    v3, _ = load_prompt("judge_v3")
    v4, _ = load_prompt("judge_v4")
    removed, added = _diff(v3.splitlines(), v4.splitlines())
    assert [r.split(" — ")[0] for r in removed] == ["TYPOLOGY_CONSISTENT", "NO_UNSUPPORTED_CLAIM"]
    starts = (
        "- TYPOLOGY_SUPPORT 는",
        "- 본문의 판정 문장",
        "TYPOLOGY_CONSISTENT — ",
        "NO_UNSUPPORTED_CLAIM — ",
    )
    assert len(added) == len(starts) and all(a.startswith(s) for a, s in zip(added, starts, strict=True))


def test_v4_registered_with_same_schema_and_frozen_hash() -> None:
    assert llm_output_model("judge_v4") is JudgeOutV2
    body = (PROMPTS / "judge_v4.md").read_bytes()
    assert FROZEN_PROMPTS["judge_v4"] == hashlib.sha256(body).hexdigest()


def test_v3_template_has_no_block_slot() -> None:
    """블록 자리는 judge_v4 에만 — v1~v3 는 계산도 안 함(05 템플릿 변수)."""
    for name in ("judge_v1", "judge_v2", "judge_v3"):
        assert "{{typology_support}}" not in (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
