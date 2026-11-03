"""SCRUM-91 — Judge 단위 테스트. docs/str/06 평가자 절.

지금 develop 에서는 `Judge.run` 호출이 `HttpLlmClient.complete_json` 안에서
`llm_output_model("judge_v1")` → `ValueError` 로 500 이 됨. 이 테스트는:

1. 가짜 LlmClient 가 `JudgeOut` 모양 JSON 을 주면 `Judge.run` 이 `LlmCheck` 5개 반환
2. `llm_output_model("judge_v1") is JudgeOut` + strict `json_schema_for`
3. 응답이 4개·중복·bad JSON 이면 `LlmInvalidOutput`
4. `narrative_v1/v2` 매핑 회귀 + 모르는 이름은 그대로 `ValueError`

SCRUM-91 /codex:rescue 전까지 (1)·(2) 는 실패해야 함.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.llm_client import LlmResult
from aml_ai.shared.infrastructure.openai_responses import json_schema_for
from aml_ai.shared.schemas.str import (
    JudgeOut,
    LlmCheckName,
    NarrativeOutV1,
    NarrativeOutV2,
    llm_output_model,
)
from aml_ai.str.infrastructure.judge import Judge

_CHECK_NAMES = [n.value for n in LlmCheckName]


def _judge_payload(scores: list[int], names: list[str] | None = None) -> str:
    names = names or _CHECK_NAMES
    checks = [
        {"check": name, "comment": f"c{i}", "score": score}
        for i, (name, score) in enumerate(zip(names, scores, strict=True))
    ]
    return json.dumps({"checks": checks})


@dataclass
class _StubLlm:
    """Judge 가 쓰는 LlmClient Protocol — complete_json 한 메서드."""

    responses: list[str]
    calls: list[dict] = field(default_factory=list)

    def complete_json(self, *, system, user, model, max_tokens, tag) -> LlmResult:
        text = self.responses[len(self.calls)]
        self.calls.append({"tag": tag, "model": model, "max_tokens": max_tokens})
        return LlmResult(text=text, model="stub", tokens_in=0, tokens_out=0, latency_ms=0)


def _judge(stub: _StubLlm) -> Judge:
    get_settings.cache_clear()
    return Judge(stub, get_settings())


def test_judge_output_schema_mapping() -> None:
    """SCRUM-91 ① — `judge_v1` 이 `JudgeOut` 로 매핑된다 (develop 에서는 ValueError)."""
    assert llm_output_model("judge_v1") is JudgeOut


def test_judge_json_schema_strict() -> None:
    """strict json_schema — 모든 object 가 additionalProperties:false + 전부 required."""
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
    stub = _StubLlm(responses=[_judge_payload([4, 5, 4, 4, 5])])
    checks = _judge(stub).run({"facts": "masked"}, [])
    assert len(checks) == 5
    assert sorted(c.check for c in checks) == sorted(LlmCheckName)
    assert all(1 <= c.score <= 5 for c in checks)
    assert stub.calls[0]["tag"] == "judge_v1"


def test_judge_wrong_count_raises_invalid_output() -> None:
    """4개만 — JudgeOut.min_length 5 로 거부."""
    partial = json.dumps(
        {"checks": [{"check": _CHECK_NAMES[i], "comment": "x", "score": 5} for i in range(4)]}
    )
    stub = _StubLlm(responses=[partial])
    with pytest.raises(LlmInvalidOutput):
        _judge(stub).run({"facts": "masked"}, [])


def test_judge_duplicate_check_raises_invalid_output() -> None:
    """같은 check 두 번 — `_each_check_once` 거부."""
    dup_names = [_CHECK_NAMES[0]] * 5
    stub = _StubLlm(responses=[_judge_payload([5, 5, 5, 5, 5], names=dup_names)])
    with pytest.raises(LlmInvalidOutput):
        _judge(stub).run({"facts": "masked"}, [])


def test_judge_bad_json_raises_invalid_output() -> None:
    stub = _StubLlm(responses=["not-json-at-all"])
    with pytest.raises(LlmInvalidOutput):
        _judge(stub).run({"facts": "masked"}, [])


def test_narrative_version_mapping_regression() -> None:
    """SCRUM-91 ① 가 narrative_v1/v2 매핑을 깨지 않는지 + 모르는 이름은 그대로 ValueError."""
    assert llm_output_model("narrative_v1") is NarrativeOutV1
    assert llm_output_model("narrative_v2") is NarrativeOutV2
    with pytest.raises(ValueError, match="unknown narrative prompt"):
        llm_output_model("nope")
