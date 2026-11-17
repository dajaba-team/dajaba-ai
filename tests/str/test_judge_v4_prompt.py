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

# develop(608c084)에서 judge_v3 로 만든 평가자 user sha256 — 블록 추가 뒤에도 같아야 함
V3_USER_SHA256 = {
    "228:fan_in": "ec6adda78049ebed89c59c6f67cf5978fdc0a5bfdac0bf471ea9510781f4b15f",
    "228:fan_in_b": "ec6adda78049ebed89c59c6f67cf5978fdc0a5bfdac0bf471ea9510781f4b15f",
    "228:fan_out": "05741c3c77eb8fb548313d7571e527d9f7e027c34040f7d5c010591f5846a78e",
    "228:cycle_nopaths": "97eefca860627fab2e5ce25e7e22fb94af6632090cf991fd1a09ba2beadfc2cd",
    "228:scatter_gather": "6662ca4bbd094d303abb45012f4a40ebe0166d140e4da96ae6e28dbb58d93f1a",
    "228:internal_transfer": "c136d7e17703abd8274e2a7dc36ca8759baa6a367a29a541e43bc03eaa33b59d",
    "228:partial_baseline": "495120b0af33f45fce8780c586247773d05c22603d8480100ffdf85e042fd051",
    "228:customer_missing": "a005b933f4646159a36db1612ca3e8e51a8da031ea7d31f7e4292aa637251f57",
    "blind2:sup_fan_in": "022c00909932a90b729e9523ac0af1be5d635f44a192381b3735bb26dd6c086d",
    "blind2:sup_fan_out": "95615859b98052f47ff9444cc428b3be103da5050c58a58ecd481ae8337dcb01",
    "blind2:sup_cycle": "2a3f9de311915c85aaaeafb78ea483390c4f051394b39f7054affaa8273b7386",
    "blind2:sup_scatter_gather": "21a8b4d8156803f36915d4fabfe1f7765cda9c5b5bc859ed46759657086b95c2",
    "blind2:uns_cycle": "8efa576e83c7640615ac96ac91a09f0c04cf5c6ca81511fc3f30612ea392e328",
    "blind2:uns_scatter_gather": "15a02fc8e69c79fa107a5f952f803ccc6c7357915f16d520c336057eb6d44d5d",
    "blind2:uns_fan_in": "629ae99f262308baf84f9a141e43568524c694ca27cc71b0b358295806f391c5",
    "blind2:mix_fan_in": "6f7c5195daa9c1691d43821382259f83f7dbb08dac9a5edcad42284575cfab62",
    "demo_7": "022c00909932a90b729e9523ac0af1be5d635f44a192381b3735bb26dd6c086d",
    "demo_48": "629ae99f262308baf84f9a141e43568524c694ca27cc71b0b358295806f391c5",
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
