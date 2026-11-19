"""SCRUM-274 — LLM 호출 추적 (docs/shared/04 "추적"). 가짜 tracer 주입, SDK 실제 전송 없음.

정상: generation 1개 · name=tag · model · usage(input·output) · request_id → 시드 trace id.
`"-"`: 시드 없음 + metadata.request_id 는 `"-"` 그대로(★A 덧붙임 2).
fail-open: 시작·update·end 예외에도 반환값 동일 · LLM 예외는 ERROR 기록 + 같은 예외 · tracing_error 한 번만.
"""

from __future__ import annotations

import logging

import pytest
from langfuse import Langfuse

from aml_ai.shared.errors import BudgetExceeded, LlmUnavailable
from aml_ai.shared.infrastructure.tracing import TracedLlmClient
from tests.shared.tracing_support import (
    FakeTracer,
    StubLlm,
    _reset_tracing,  # noqa: F401 — autouse
    request_id,
    tracing_records,
)

CALL = {
    "system": "SYSTEM-PROMPT-BODY",
    "user": "USER-PROMPT-BODY",
    "model": "model-requested",
    "max_tokens": 900,
    "tag": "judge_v4",
}


def _traced(tracer: FakeTracer, inner: StubLlm | None = None) -> tuple[TracedLlmClient, StubLlm]:
    stub = inner or StubLlm()
    return TracedLlmClient(stub, tracer, server_version="test-sv"), stub


# ───────── 정상 ─────────


def test_one_call_records_one_generation() -> None:
    tracer = FakeTracer()
    client, stub = _traced(tracer)
    with request_id("rid-274-a"):
        out = client.complete_json(**CALL)

    assert out is stub.result
    assert stub.calls == [{**CALL, "timeout_s": None}]  # total_timeout_s 는 값 없으면 안 넘김
    assert len(tracer.observations) == 1
    obs = tracer.observations[0]
    final = obs.merged()
    assert obs.start["as_type"] == "generation"
    assert obs.start["name"] == "judge_v4"
    assert obs.start["trace_context"] == {"trace_id": Langfuse.create_trace_id(seed="rid-274-a")}
    assert obs.start["input"] == {"system": "SYSTEM-PROMPT-BODY", "user": "USER-PROMPT-BODY"}
    assert final["model"] == "stub-model-returned"  # API 가 돌려준 모델(04 llm_model 과 같은 기준)
    assert final["output"] == '{"ok": true}'
    assert final["usage_details"] == {"input": 120, "output": 45}
    assert final.get("level") in (None, "DEFAULT")
    assert final["metadata"] == {
        "request_id": "rid-274-a",
        "prompt_version": "judge_v4",
        "server_version": "test-sv",
    }
    assert obs.ended == 1


def test_timeout_s_is_passed_through() -> None:
    client, stub = _traced(FakeTracer())
    client.complete_json(**CALL, timeout_s=12.5)
    assert stub.calls[0]["timeout_s"] == 12.5


def test_total_timeout_s_is_passed_through() -> None:
    """SCRUM-290 추가 검토 1 — 질문 답변의 호출 전체 제한도 그대로 넘김."""
    client, stub = _traced(FakeTracer())
    client.complete_json(**CALL, timeout_s=10.0, total_timeout_s=10.0)
    assert stub.calls[0]["total_timeout_s"] == 10.0


def test_dash_request_id_has_no_seed_but_keeps_metadata() -> None:
    """요청 밖 호출(request_id `"-"`) — trace_context 없음, metadata.request_id 는 `"-"` 그대로."""
    tracer = FakeTracer()
    client, _ = _traced(tracer)
    with request_id("-"):
        client.complete_json(**CALL)
    obs = tracer.observations[0]
    assert obs.start.get("trace_context") is None
    assert obs.merged()["metadata"]["request_id"] == "-"


# ───────── 실패 — LLM 예외는 그대로 ─────────


@pytest.mark.parametrize("exc", [LlmUnavailable("llm unavailable"), BudgetExceeded("budget")])
def test_llm_error_is_recorded_and_reraised_unchanged(exc: Exception) -> None:
    tracer = FakeTracer()
    client, _ = _traced(tracer, StubLlm(exc=exc))
    with request_id("rid-274-err"), pytest.raises(type(exc)) as excinfo:
        client.complete_json(**CALL)

    assert excinfo.value is exc
    final = tracer.observations[0].merged()
    assert final["level"] == "ERROR"
    assert final["status_message"] == type(exc).__name__  # 종류 이름만, 메시지 원문 없음
    assert "output" not in final
    assert tracer.observations[0].ended == 1


# ───────── fail-open — 기록 실패는 결과를 바꾸지 않음 ─────────


@pytest.mark.parametrize("where", ["start", "update", "end"])
def test_tracer_errors_do_not_change_result(where: str) -> None:
    boom = RuntimeError("tracer down")
    tracer = FakeTracer(**{f"raise_on_{where}": boom})
    client, stub = _traced(tracer)
    out = client.complete_json(**CALL)
    assert out is stub.result
    assert len(stub.calls) == 1  # 기록이 실패해도 LLM 은 한 번만 부름


def test_tracer_error_does_not_hide_llm_error() -> None:
    exc = LlmUnavailable("llm unavailable")
    tracer = FakeTracer(raise_on_update=RuntimeError("tracer down"))
    client, _ = _traced(tracer, StubLlm(exc=exc))
    with pytest.raises(LlmUnavailable) as excinfo:
        client.complete_json(**CALL)
    assert excinfo.value is exc


def test_same_tracing_error_warns_once_per_process(caplog: pytest.LogCaptureFixture) -> None:
    """★B 답 2 — 같은 reason 은 프로세스당 한 번만 경고."""
    client, _ = _traced(FakeTracer(raise_on_start=RuntimeError("tracer down")))
    with caplog.at_level(logging.WARNING):
        for _ in range(3):
            client.complete_json(**CALL)
    records = tracing_records(caplog, "tracing_error")
    assert len(records) == 1
    assert records[0].reason == "RuntimeError"
    assert "tracer down" not in caplog.text
    assert "PROMPT-BODY" not in caplog.text
