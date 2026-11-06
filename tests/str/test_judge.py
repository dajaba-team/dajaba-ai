"""SCRUM-91 — Judge 스키마 매핑·거부·회귀 테스트. docs/str/06.

SCRUM-92 재시도·메타·로그 안전성은 `test_judge_retry.py`.
"""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.openai_responses import json_schema_for
from aml_ai.shared.schemas.str import (
    JudgeOut,
    LlmCheckName,
    NarrativeOutV1,
    NarrativeOutV2,
    llm_output_model,
)
from aml_ai.str.infrastructure.judge import JudgeResult
from tests.str.judge_support import CHECK_NAMES, StubLlm, judge_payload, make_judge


def test_judge_output_schema_mapping() -> None:
    assert llm_output_model("judge_v1") is JudgeOut


def test_judge_json_schema_strict() -> None:
    schema = json_schema_for(JudgeOut, name="judge_v1")
    assert schema["name"] == "judge_v1"

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"].keys())
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(schema["schema"])


def test_judge_passes_valid_output() -> None:
    stub = StubLlm(responses=[judge_payload([4, 5, 4, 4, 5])])
    result = make_judge(stub).run({"facts": "masked"}, [])
    assert isinstance(result, JudgeResult)
    assert len(result.checks) == 5
    assert sorted(c.check for c in result.checks) == sorted(LlmCheckName)
    assert all(1 <= c.score <= 5 for c in result.checks)
    assert stub.calls[0]["tag"] == "judge_v1"


def test_judge_wrong_count_raises_invalid_output() -> None:
    partial = json.dumps(
        {"checks": [{"check": CHECK_NAMES[i], "comment": "x", "score": 5} for i in range(4)]}
    )
    # 1번째 실패 뒤 재시도도 같은 모양이면 결국 LlmInvalidOutput (2번 호출)
    stub = StubLlm(responses=[partial, partial])
    with pytest.raises(LlmInvalidOutput):
        make_judge(stub).run({"facts": "masked"}, [])


def test_judge_duplicate_check_raises_invalid_output() -> None:
    dup_names = [CHECK_NAMES[0]] * 5
    payload = judge_payload([5, 5, 5, 5, 5], names=dup_names)
    stub = StubLlm(responses=[payload, payload])
    with pytest.raises(LlmInvalidOutput):
        make_judge(stub).run({"facts": "masked"}, [])


def test_judge_bad_json_raises_invalid_output() -> None:
    stub = StubLlm(responses=["not-json-at-all", "not-json-at-all"])
    with pytest.raises(LlmInvalidOutput):
        make_judge(stub).run({"facts": "masked"}, [])


def test_narrative_version_mapping_regression() -> None:
    assert llm_output_model("narrative_v1") is NarrativeOutV1
    assert llm_output_model("narrative_v2") is NarrativeOutV2
    with pytest.raises(ValueError, match="unknown prompt name"):
        llm_output_model("nope")
