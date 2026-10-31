"""생성기 — 활성 버전과 다른 섹션 집합 응답은 재생성 뒤 LlmInvalidOutput (SCRUM-47).

Codex adversarial 지적: `_validate_result` 가 공용 `NarrativeOut` 이면 v2 모드에서 v1 응답이 통과한다.
`llm_output_model(prompt_name)` 로 활성 버전 모델만 받는지 양방향으로 확인.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import LlmInvalidOutput
from aml_ai.shared.infrastructure.llm_client import LlmResult
from aml_ai.str.infrastructure.narrative_generator import NarrativeGenerator

_FAR_FUTURE = 10**9

_V1_NARRATIVE = {
    "narrative": [
        {"section": "SUMMARY", "text": "요약.", "cites": ["inbound.count"]},
        {"section": "WHO", "text": "누구.", "cites": []},
        {"section": "WHAT_WHEN_WHERE", "text": "언제.", "cites": ["period"]},
        {"section": "HOW", "text": "어떻게.", "cites": []},
        {"section": "WHY_SUSPICIOUS", "text": "왜.", "cites": []},
        {"section": "CONCLUSION", "text": "결론.", "cites": []},
    ]
}
_V2_NARRATIVE = {
    "narrative": [
        {"section": "SUBJECT", "text": "대상자.", "cites": []},
        {"section": "DATE", "text": "일자.", "cites": ["period"]},
        {"section": "PLACE", "text": "장소.", "cites": []},
        {"section": "INSTRUMENT", "text": "수단.", "cites": []},
        {"section": "METHOD", "text": "방법.", "cites": []},
        {"section": "GROUNDS", "text": "사유.", "cites": ["inbound.count"]},
        {"section": "OPINION", "text": "결론.", "cites": []},
    ]
}


@dataclass
class _StubLlm:
    responses: list[str]
    calls: int = 0

    def complete_json(self, *, system, user, model, max_tokens, tag) -> LlmResult:
        text = self.responses[self.calls]
        self.calls += 1
        return LlmResult(text=text, model="stub", tokens_in=0, tokens_out=0, latency_ms=0)


def _generator(prompt_name: str, llm: _StubLlm) -> NarrativeGenerator:
    get_settings.cache_clear()
    g = NarrativeGenerator.__new__(NarrativeGenerator)
    g._llm = llm
    g._s = get_settings()
    g.prompt_version = prompt_name
    g._clock = time.monotonic
    from aml_ai.str.infrastructure.narrative_generator import load_prompt

    g._system, g._user_tpl = load_prompt(
        "narrative_v1"
    )  # 템플릿 자체는 v1 로 — 응답 집합만 다른지 보는 테스트
    return g


def _run(g: NarrativeGenerator) -> None:
    g.generate({"a": 1}, ["inbound.count", "period"], [], [], None, deadline=g._clock() + _FAR_FUTURE)


def test_v2_mode_rejects_v1_response_twice() -> None:
    """prompt_version='narrative_v2' 에 완전한 v1 집합 응답 — 두 번 다 거부, LlmInvalidOutput."""
    llm = _StubLlm(responses=[json.dumps(_V1_NARRATIVE), json.dumps(_V1_NARRATIVE)])
    g = _generator("narrative_v2", llm)
    with pytest.raises(LlmInvalidOutput):
        _run(g)
    assert llm.calls == 2  # 재생성까지 소진


def test_v2_mode_accepts_v2_response_after_v1_retry() -> None:
    """v2 모드: 첫 응답 v1(거부) → 재생성 v2 → 성공."""
    llm = _StubLlm(responses=[json.dumps(_V1_NARRATIVE), json.dumps(_V2_NARRATIVE)])
    g = _generator("narrative_v2", llm)
    _run(g)
    assert llm.calls == 2


def test_v1_mode_rejects_v2_response_twice() -> None:
    """prompt_version='narrative_v1' 에 완전한 v2 집합 응답 — 두 번 다 거부."""
    llm = _StubLlm(responses=[json.dumps(_V2_NARRATIVE), json.dumps(_V2_NARRATIVE)])
    g = _generator("narrative_v1", llm)
    with pytest.raises(LlmInvalidOutput):
        _run(g)
    assert llm.calls == 2


def test_v1_mode_accepts_v1_response_after_v2_retry() -> None:
    """v1 모드: 첫 응답 v2(거부) → 재생성 v1 → 성공."""
    llm = _StubLlm(responses=[json.dumps(_V2_NARRATIVE), json.dumps(_V1_NARRATIVE)])
    g = _generator("narrative_v1", llm)
    _run(g)
    assert llm.calls == 2
