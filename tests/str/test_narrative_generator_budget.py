"""NarrativeGenerator 시간 예산 (SCRUM-45) — 가짜 시계로 선체크·재생성 경계·토큰 합산.

경계는 `.env`·설정 숫자가 아니라 **`get_settings()` 값에서 계산**한다 — 운영자가 숫자를
바꿔도(`DRAFT_BUDGET_S`·`LLM_TIMEOUT_S`·`REGEN_MIN_REMAINING_S`) 테스트는 그대로 돈다.
불변식(draft_budget_s·regen_min_remaining_s >= llm_timeout_s, SCRUM-45) 이 기동 때 걸러진다.

이 파일은 `test_narrative_generator.py` 와 분리 — 기존 분기(재시도·cites·fact_keys 전달)와
시간 예산 분기를 섞으면 한 파일이 200줄 넘고 `on_call`·`LlmResult` 수용 Stub 이 기존 테스트에
불필요한 복잡도를 가져온다 (str/01 "함수·파일 모양").
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import LlmInvalidOutput, LlmUnavailable
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
SCOPED_JSON = json.dumps(NARRATIVE_SCOPED)


class _FakeClock:
    """`Callable[[], float]`. `advance(delta)` 로 수동 전진."""

    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, delta: float) -> None:
        self.t += delta


@dataclass
class StubLlm:
    """responses 는 str 또는 LlmResult. on_call 은 호출 **뒤** 실행(가짜 시계 전진 등)."""

    responses: list[str | LlmResult]
    calls: int = 0
    on_call: Callable[[], None] | None = field(default=None)

    def complete_json(self, *, system, user, model, max_tokens, tag) -> LlmResult:
        r = self.responses[self.calls]
        self.calls += 1
        if self.on_call is not None:
            self.on_call()
        if isinstance(r, LlmResult):
            return r
        return LlmResult(text=r, model="stub", tokens_in=0, tokens_out=0, latency_ms=0)


@pytest.fixture
def gen() -> NarrativeGenerator:
    get_settings.cache_clear()
    return NarrativeGenerator.__new__(NarrativeGenerator)


def _bind(g: NarrativeGenerator, llm: StubLlm, *, clock: Callable[[], float]) -> NarrativeGenerator:
    from aml_ai.str.infrastructure.narrative_generator import load_prompt

    g._llm = llm
    g._s = get_settings()
    g.prompt_version = "narrative_v1"
    g._system, g._user_tpl = load_prompt("narrative_v1")
    g._clock = clock
    return g


def _generate(g: NarrativeGenerator, *, deadline: float):
    return g.generate({"a": 1}, ["inbound.count", "period"], [], [], None, deadline=deadline)


def test_preflight_blocks_when_budget_below_llm_timeout(gen: NarrativeGenerator) -> None:
    """선체크 아래 — 남은 예산 < `llm_timeout_s` → LLM 호출 0회, LlmUnavailable."""
    settings = get_settings()
    clock = _FakeClock()
    llm = StubLlm(responses=[SCOPED_JSON])
    g = _bind(gen, llm, clock=clock)
    deadline = clock() + settings.llm_timeout_s - 0.1
    with pytest.raises(LlmUnavailable):
        _generate(g, deadline=deadline)
    assert llm.calls == 0


def test_preflight_allows_at_llm_timeout_boundary(gen: NarrativeGenerator) -> None:
    """선체크 경계 — 남은 예산 == `llm_timeout_s` → LLM 호출 1회·성공."""
    settings = get_settings()
    clock = _FakeClock()
    llm = StubLlm(responses=[SCOPED_JSON])
    g = _bind(gen, llm, clock=clock)
    deadline = clock() + settings.llm_timeout_s
    out = _generate(g, deadline=deadline)
    assert llm.calls == 1
    assert out.prompt_version == "narrative_v1"


def test_regen_at_boundary(gen: NarrativeGenerator) -> None:
    """재생성 경계 — 첫 호출(llm_timeout_s 소요 가정) 뒤 남은 == `regen_min_remaining_s` → 재생성·성공."""
    settings = get_settings()
    clock = _FakeClock()
    llm = StubLlm(
        responses=["not json", SCOPED_JSON],
        on_call=lambda: clock.advance(settings.llm_timeout_s),
    )
    g = _bind(gen, llm, clock=clock)
    deadline = clock() + settings.llm_timeout_s + settings.regen_min_remaining_s
    out = _generate(g, deadline=deadline)
    assert llm.calls == 2
    assert out.prompt_version == "narrative_v1"


def test_no_regen_below_boundary(gen: NarrativeGenerator) -> None:
    """재생성 경계 아래 — 첫 호출 뒤 남은 == `regen_min_remaining_s - 0.1` → 재생성 없이 LlmInvalidOutput."""
    settings = get_settings()
    clock = _FakeClock()
    llm = StubLlm(
        responses=["not json", SCOPED_JSON],
        on_call=lambda: clock.advance(settings.llm_timeout_s + 0.1),
    )
    g = _bind(gen, llm, clock=clock)
    deadline = clock() + settings.llm_timeout_s + settings.regen_min_remaining_s
    with pytest.raises(LlmInvalidOutput):
        _generate(g, deadline=deadline)
    assert llm.calls == 1


def test_sums_tokens_and_latency_on_retry(gen: NarrativeGenerator) -> None:
    """성공 시 tokens_in·tokens_out·latency_ms 는 호출한 횟수의 합 (SCRUM-15 M5, SCRUM-45)."""
    clock = _FakeClock()
    first = LlmResult(text="not json", model="stub", tokens_in=100, tokens_out=50, latency_ms=1000)
    second = LlmResult(text=SCOPED_JSON, model="stub", tokens_in=120, tokens_out=80, latency_ms=1500)
    llm = StubLlm(responses=[first, second])
    g = _bind(gen, llm, clock=clock)
    out = _generate(g, deadline=clock() + 10**9)
    assert llm.calls == 2
    assert out.tokens_in == 220  # 100 + 120
    assert out.tokens_out == 130  # 50 + 80
    assert out.latency_ms == 2500  # 1000 + 1500
