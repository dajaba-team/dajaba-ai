"""SCRUM-61 — judge_v2 스키마·sections 검증·FACT_KEYS 전달·재시도. docs/str/06·05.

- `JudgeOutV2` 정상·중복·누락·빈 cites
- 요청 섹션 집합 ≠ 응답 sections → `LlmInvalidOutput` → 재시도 1회 → VERIFY_UNAVAILABLE
- user 문자열에 FACT_KEYS 가 생성기와 **같은 모양**(`"\\n".join(keys) or "(없음)"`)으로 들어감
- `_LLM_OUTPUT_MODELS["judge_v2"] is JudgeOutV2`

구현 전에 쓴 테스트 — develop 에서는 import·스키마·동작이 없어 전부 실패.
"""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.schemas.str import (
    JudgeOutV2,
    SectionV1,
    SectionV2,
    llm_output_model,
)
from tests.str.judge_support import CHECK_NAMES, StubLlm, make_judge

_V1_SECTIONS = [s.value for s in SectionV1]
_V2_SECTIONS = [s.value for s in SectionV2]


def _v2_payload(
    scores: list[int] | None = None,
    sections: list[str] | None = None,
    cites_by_section: dict[str, list[str]] | None = None,
) -> str:
    scores = scores or [4, 5, 4, 4, 5]
    sections = sections or _V1_SECTIONS
    cites_by_section = cites_by_section or {s: [] for s in sections}
    checks = [
        {"check": name, "comment": f"c{i}", "score": s}
        for i, (name, s) in enumerate(zip(CHECK_NAMES, scores, strict=True))
    ]
    section_blocks = [{"section": s, "cites": cites_by_section.get(s, [])} for s in sections]
    return json.dumps({"checks": checks, "sections": section_blocks})


def test_judge_v2_output_schema_mapping() -> None:
    """`llm_output_model("judge_v2") is JudgeOutV2`. narrative_version 매핑 한 줄."""
    assert llm_output_model("judge_v2") is JudgeOutV2


def test_judge_v2_valid_v1_sections() -> None:
    """정상 v1 6섹션·cites 빈 배열 → JudgeResult(sections 6, checks 5)."""
    stub = StubLlm(responses=[_v2_payload(sections=_V1_SECTIONS)])
    result = make_judge(stub, prompt_name="judge_v2", request_sections=_V1_SECTIONS).run(
        {"facts": "masked"}, [], fact_keys=["period", "inbound.count"]
    )
    assert len(result.checks) == 5
    assert [s.section.value for s in result.sections] == _V1_SECTIONS


def test_judge_v2_sections_mismatch_retries_then_fails() -> None:
    """요청 v2(7) 인데 응답 sections 가 v1(6) → LlmInvalidOutput → 재시도 뒤 또 실패 → 호출 2번."""
    bad = _v2_payload(sections=_V1_SECTIONS)
    stub = StubLlm(responses=[bad, bad])
    with pytest.raises(LlmInvalidOutput):
        make_judge(stub, prompt_name="judge_v2", request_sections=_V2_SECTIONS).run(
            {"facts": "masked"}, [], fact_keys=["period"], deadline=None
        )
    assert len(stub.calls) == 2


def test_judge_v2_sections_duplicate_raises() -> None:
    """같은 섹션이 두 번 → 스키마 실패."""
    dup = [_V1_SECTIONS[0]] * 6
    stub = StubLlm(responses=[_v2_payload(sections=dup), _v2_payload(sections=dup)])
    with pytest.raises(LlmInvalidOutput):
        make_judge(stub, prompt_name="judge_v2", request_sections=_V1_SECTIONS).run(
            {"facts": "masked"}, [], fact_keys=[], deadline=None
        )


def test_judge_v2_user_has_fact_keys_same_shape() -> None:
    """user 문자열에 FACT_KEYS 가 `'\\n'.join(keys) or '(없음)'` 모양으로 포함 — 생성기와 같은 모양."""
    stub = StubLlm(responses=[_v2_payload(sections=_V1_SECTIONS)])
    keys = ["period", "inbound.count", "subject.account_key"]
    make_judge(stub, prompt_name="judge_v2", request_sections=_V1_SECTIONS).run(
        {"facts": "masked"}, [], fact_keys=keys
    )
    assert stub.calls, "호출 안 됨"
    user = stub.calls[0]["user"]
    expected = "\n".join(keys)
    assert expected in user, f"FACT_KEYS 블록 없음: user={user[:400]}..."


def test_judge_v2_user_empty_fact_keys_says_none() -> None:
    """빈 키 → `(없음)` 로 표시(생성기와 같은 규칙)."""
    stub = StubLlm(responses=[_v2_payload(sections=_V1_SECTIONS)])
    make_judge(stub, prompt_name="judge_v2", request_sections=_V1_SECTIONS).run(
        {"facts": "masked"}, [], fact_keys=[]
    )
    assert "(없음)" in stub.calls[0]["user"]


def test_judge_v2_cites_allowed_values() -> None:
    """출력 sections 의 cites 는 임의 문자열 — 스키마는 fact_keys 밖 키를 거부하지 않음(verify 가 걸러냄)."""
    payload = _v2_payload(
        sections=_V1_SECTIONS,
        cites_by_section={_V1_SECTIONS[0]: ["period", "no_such_fact_key"]},
    )
    stub = StubLlm(responses=[payload])
    result = make_judge(stub, prompt_name="judge_v2", request_sections=_V1_SECTIONS).run(
        {"facts": "masked"}, [], fact_keys=["period"]
    )
    first_cites = [s.cites for s in result.sections if s.section.value == _V1_SECTIONS[0]][0]
    assert "period" in first_cites
    assert "no_such_fact_key" in first_cites  # 스키마는 통과(verify 쪽에서 필터)
