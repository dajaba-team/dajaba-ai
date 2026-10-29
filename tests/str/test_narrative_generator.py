"""NarrativeGenerator — 재시도·cites ⊆ fact_keys 검사·fact_keys 전달.

RecordedLlmClient 경로는 녹화 파일 커밋 뒤에만 재현되므로 여기선 stub LlmClient 로 분기 전부 검사.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.llm_client import LlmResult
from aml_ai.str.infrastructure.narrative_generator import NarrativeGenerator

NARRATIVE_SCOPED = {
    "narrative": [
        {"section": "SUMMARY", "text": "요약.", "cites": ["inbound.count"]},
        {"section": "WHO", "text": "누구.", "cites": []},
        {"section": "WHAT_WHEN_WHERE", "text": "언제.", "cites": ["period"]},
        {"section": "HOW", "text": "어떻게.", "cites": []},
        {"section": "WHY_SUSPICIOUS", "text": "왜.", "cites": []},
        {"section": "CONCLUSION", "text": "결론.", "cites": []},
    ]
}
NARRATIVE_OOS = {
    "narrative": [
        {"section": "SUMMARY", "text": "요약.", "cites": ["inbound.count", "bogus.key"]},
        *NARRATIVE_SCOPED["narrative"][1:],
    ]
}


@dataclass
class StubLlm:
    responses: list[str]
    calls: int = 0

    def complete_json(self, *, system, user, model, max_tokens, tag) -> LlmResult:
        text = self.responses[self.calls]
        self.calls += 1
        return LlmResult(text=text, model="stub", tokens_in=0, tokens_out=0, latency_ms=0)


@pytest.fixture
def gen() -> NarrativeGenerator:
    get_settings.cache_clear()
    return NarrativeGenerator.__new__(NarrativeGenerator)  # 아래 _bind 로 수동 조립


def _bind(g: NarrativeGenerator, llm: StubLlm) -> NarrativeGenerator:
    from aml_ai.str.infrastructure.narrative_generator import load_prompt

    g._llm = llm
    g._s = get_settings()
    g.prompt_version = "narrative_v1"
    g._system, g._user_tpl = load_prompt("narrative_v1")
    return g


def test_generator_passes_fact_keys_through_user(gen: NarrativeGenerator) -> None:
    """fact_keys 가 user 프롬프트의 FACT_KEYS 블록에 들어간다."""
    llm = StubLlm(responses=[json.dumps(NARRATIVE_SCOPED)])
    g = _bind(gen, llm)
    captured = {}

    def capture(**kw):
        captured["user"] = kw["user"]
        return LlmResult(
            text=json.dumps(NARRATIVE_SCOPED), model="stub", tokens_in=0, tokens_out=0, latency_ms=0
        )

    g._llm = type("Capt", (), {"complete_json": lambda self, **kw: capture(**kw)})()
    g.generate({"a": 1}, ["inbound.count", "period", "subject"], [], [], None)
    assert "inbound.count\nperiod\nsubject" in captured["user"]


def test_generator_valid_passes(gen: NarrativeGenerator) -> None:
    llm = StubLlm(responses=[json.dumps(NARRATIVE_SCOPED)])
    g = _bind(gen, llm)
    out = g.generate({"a": 1}, ["inbound.count", "period"], [], [], None)
    assert out.prompt_version == "narrative_v1"
    assert llm.calls == 1


def test_generator_retries_on_schema_invalid(gen: NarrativeGenerator) -> None:
    """1회 실패 → 1회 재시도 → 성공."""
    llm = StubLlm(responses=["not json at all", json.dumps(NARRATIVE_SCOPED)])
    g = _bind(gen, llm)
    out = g.generate({"a": 1}, ["inbound.count", "period"], [], [], None)
    assert out.narrative[0].section.value == "SUMMARY"
    assert llm.calls == 2


def test_generator_rejects_cites_out_of_scope(gen: NarrativeGenerator) -> None:
    """cites 가 FACT_KEYS 밖이면 스키마 실패와 같은 취급(재시도도 소진), 최종 LlmInvalidOutput."""
    llm = StubLlm(responses=[json.dumps(NARRATIVE_OOS), json.dumps(NARRATIVE_OOS)])
    g = _bind(gen, llm)
    with pytest.raises(LlmInvalidOutput):
        g.generate({"a": 1}, ["inbound.count", "period"], [], [], None)
    assert llm.calls == 2


def test_generator_retries_oos_then_succeeds(gen: NarrativeGenerator) -> None:
    """첫 응답 cites 밖 → 재시도 성공."""
    llm = StubLlm(responses=[json.dumps(NARRATIVE_OOS), json.dumps(NARRATIVE_SCOPED)])
    g = _bind(gen, llm)
    out = g.generate({"a": 1}, ["inbound.count", "period"], [], [], None)
    assert llm.calls == 2
    assert all(c in {"inbound.count", "period"} for s in out.narrative for c in s.cites)
