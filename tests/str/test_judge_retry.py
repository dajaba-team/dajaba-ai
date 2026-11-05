"""SCRUM-92 — Judge 1회 재시도·메타·max_tokens·로그 안전성. docs/str/06.

- `Judge.run()` → `JudgeResult(checks, meta)` (meta = JudgeMeta 6필드).
- 스키마 실패 1회 재시도: 남은 예산 ≥ `LLM_TIMEOUT_S` 일 때만.
- `LlmUnavailable` 은 재시도 없음.
- 토큰·지연 합(실패한 1번째 포함), 모델은 **마지막** 값.
- `max_tokens = JUDGE_MAX_TOKENS` 상수.
- 실패 로그에 comment·본문 안 들어감(SCRUM-15 adversarial H2).
"""

from __future__ import annotations

import logging
import time

import pytest

from aml_ai.shared.errors import BudgetExceeded, LlmInvalidOutput, LlmUnavailable
from aml_ai.str.domain.constants import JUDGE_MAX_TOKENS
from tests.str.judge_support import (
    StubCall,
    StubLlm,
    generous_deadline,
    judge_payload,
    make_judge,
)


def test_judge_meta_populated_single_attempt() -> None:
    """정상 — 1회 호출 → meta.attempts=1, 토큰·지연·모델은 1회분."""
    stub = StubLlm(
        call_specs=[
            StubCall(
                text=judge_payload([4, 5, 4, 4, 5]),
                model="gpt-5-judge-sol",
                tokens_in=1800,
                tokens_out=600,
                latency_ms=8000,
            )
        ]
    )
    result = make_judge(stub).run({"facts": "masked"}, [])
    assert result.meta.llm_model == "gpt-5-judge-sol"
    assert result.meta.prompt_version == "judge_v1"
    assert result.meta.tokens_in == 1800
    assert result.meta.tokens_out == 600
    assert result.meta.latency_ms == 8000
    assert result.meta.attempts == 1


def test_judge_max_tokens_from_constant() -> None:
    """stub.calls[0]['max_tokens'] == JUDGE_MAX_TOKENS (상수 — 지금 4000)."""
    stub = StubLlm(responses=[judge_payload([4, 5, 4, 4, 5])])
    make_judge(stub).run({"facts": "masked"}, [])
    assert stub.calls[0]["max_tokens"] == JUDGE_MAX_TOKENS


def test_judge_schema_fail_then_ok_retries_once() -> None:
    """★ 진희 필수 — 스키마 실패 1번째 → 2번째 정상. 호출 2번, 토큰·지연 합, 모델 = 마지막."""
    stub = StubLlm(
        call_specs=[
            StubCall(text="not-json", model="m1", tokens_in=1200, tokens_out=300, latency_ms=3000),
            StubCall(
                text=judge_payload([4, 5, 4, 4, 5]),
                model="m2-last",
                tokens_in=1800,
                tokens_out=600,
                latency_ms=5000,
            ),
        ]
    )
    result = make_judge(stub).run({"facts": "masked"}, [], deadline=generous_deadline())

    assert len(stub.calls) == 2
    assert len(result.checks) == 5
    assert result.meta.attempts == 2
    assert result.meta.tokens_in == 3000
    assert result.meta.tokens_out == 900
    assert result.meta.latency_ms == 8000
    assert result.meta.llm_model == "m2-last"


def test_judge_schema_fail_twice_two_calls_only() -> None:
    """★ 진희 필수 — 두 번 다 스키마 실패 → LlmInvalidOutput, 호출 2번(3번 아님)."""
    stub = StubLlm(
        call_specs=[
            StubCall(text="not-json", tokens_in=1200, tokens_out=300, latency_ms=3000),
            StubCall(text="still-not-json", tokens_in=1300, tokens_out=400, latency_ms=4000),
        ]
    )
    with pytest.raises(LlmInvalidOutput):
        make_judge(stub).run({"facts": "masked"}, [], deadline=generous_deadline())
    assert len(stub.calls) == 2


def test_judge_unavailable_no_retry() -> None:
    """★ 진희 필수 — 1번째 LlmUnavailable → 재시도 없이 바로 올림, 호출 1번."""
    stub = StubLlm(
        call_specs=[
            StubCall(text="unused", exc=LlmUnavailable("llm unavailable")),
            StubCall(text=judge_payload([4, 5, 4, 4, 5])),
        ]
    )
    with pytest.raises(LlmUnavailable):
        make_judge(stub).run({"facts": "masked"}, [], deadline=generous_deadline())
    assert len(stub.calls) == 1


def test_judge_no_budget_no_retry() -> None:
    """남은 예산 < LLM_TIMEOUT_S 면 스키마 실패 뒤 재시도 없이 바로 LlmInvalidOutput, 호출 1번."""
    stub = StubLlm(
        call_specs=[
            StubCall(text="not-json", tokens_in=1200, tokens_out=300, latency_ms=3000),
            StubCall(text=judge_payload([4, 5, 4, 4, 5])),
        ]
    )
    # deadline 을 "이미 지남" 수준으로 — 남은 예산 0
    deadline = time.monotonic() - 1.0
    with pytest.raises(LlmInvalidOutput):
        make_judge(stub).run({"facts": "masked"}, [], deadline=deadline)
    assert len(stub.calls) == 1


# ───────── SCRUM-144 — 2차 complete_json 예외 시 1차 토큰 보존 ─────────


@pytest.mark.parametrize(
    "exc",
    [LlmUnavailable("timeout"), BudgetExceeded("quota"), LlmInvalidOutput("http 4xx")],
    ids=["LlmUnavailable", "BudgetExceeded", "LlmInvalidOutput_http"],
)
def test_judge_2nd_call_exception_preserves_1st_meta(exc) -> None:
    """SCRUM-144 — 2차 complete_json 이 예외로 끝나면 1차 토큰이 exc.judge_meta 로 올라온다."""
    stub = StubLlm(
        call_specs=[
            StubCall(text="not-json", tokens_in=1200, tokens_out=300, latency_ms=3000),
            StubCall(text="unused", exc=exc),
        ]
    )
    with pytest.raises(type(exc)) as excinfo:
        make_judge(stub).run({"facts": "masked"}, [], deadline=generous_deadline())
    assert len(stub.calls) == 2
    meta = getattr(excinfo.value, "judge_meta", None)
    assert meta is not None and meta.attempts == 2
    assert meta.tokens_in == 1200 and meta.tokens_out == 300 and meta.latency_ms == 3000


def test_judge_1st_call_exception_no_meta() -> None:
    """회귀 — 첫 호출 자체가 예외면 results 비어 judge_meta 안 붙음(지금 동작 그대로)."""
    stub = StubLlm(
        call_specs=[
            StubCall(text="unused", exc=LlmUnavailable("llm unavailable")),
            StubCall(text=judge_payload([4, 5, 4, 4, 5])),
        ]
    )
    with pytest.raises(LlmUnavailable) as excinfo:
        make_judge(stub).run({"facts": "masked"}, [], deadline=generous_deadline())
    assert len(stub.calls) == 1
    assert getattr(excinfo.value, "judge_meta", None) is None


def test_judge_no_budget_attempts_stays_one() -> None:
    """회귀 (SCRUM-144) — 1차 스키마 실패 + 예산 부족으로 2차 안 부르고 raise → attempts=1 그대로."""
    stub = StubLlm(
        call_specs=[
            StubCall(text="not-json", tokens_in=1200, tokens_out=300, latency_ms=3000),
            StubCall(text=judge_payload([4, 5, 4, 4, 5])),
        ]
    )
    deadline = time.monotonic() - 1.0
    with pytest.raises(LlmInvalidOutput) as excinfo:
        make_judge(stub).run({"facts": "masked"}, [], deadline=deadline)
    assert len(stub.calls) == 1
    meta = getattr(excinfo.value, "judge_meta", None)
    assert meta is not None
    assert meta.attempts == 1, "예산 부족으로 2차 안 보냈으니 attempts=1"


def test_judge_fail_log_safe(caplog: pytest.LogCaptureFixture) -> None:
    """실패 로그에 comment·본문·exception detail 안 들어감 (SCRUM-15 adversarial H2)."""
    sensitive = '{"checks":[{"check":"X","comment":"42,750.50 USD leaked","score":5}]}'
    stub = StubLlm(
        call_specs=[
            StubCall(text=sensitive, tokens_in=1200, tokens_out=300, latency_ms=3000),
            StubCall(text="not-json-either", tokens_in=1300, tokens_out=400, latency_ms=4000),
        ]
    )
    with (
        caplog.at_level(logging.WARNING, logger="aml_ai.str.infrastructure.judge"),
        pytest.raises(LlmInvalidOutput),
    ):
        make_judge(stub).run({"facts": "masked"}, [], deadline=generous_deadline())

    for record in caplog.records:
        assert "42,750.50" not in record.getMessage()
        for v in record.__dict__.values():
            assert "42,750.50" not in str(v)
