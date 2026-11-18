"""SCRUM-274 — 검증 평가자 3표(judge_vote 스레드 3개)가 같은 request_id 면 한 trace (docs/shared/04 "추적").

trace id 는 OTel 현재 컨텍스트가 아니라 `trace_context` 로 직접 넘긴다 — 스레드가 달라도 같은 값(★A ③).
"""

from __future__ import annotations

from langfuse import Langfuse

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.tracing import TracedLlmClient
from aml_ai.str.infrastructure.judge import Judge
from tests.shared.tracing_support import (
    FakeTracer,
    _reset_tracing,  # noqa: F401 — autouse
    request_id,
)
from tests.str.judge_votes_support import ThreadSafeStub, VoteCall, dummy_narrative, v3_payload


def test_three_votes_share_one_trace() -> None:
    stub = ThreadSafeStub([VoteCall(text=v3_payload([5, 5, 5, 5, 5])) for _ in range(3)])
    tracer = FakeTracer()
    traced = TracedLlmClient(stub, tracer, server_version="test-sv")
    get_settings.cache_clear()
    judge = Judge(traced, get_settings(), prompt_name="judge_v3", votes=3, schema_retry=0)

    with request_id("rid-274-votes"):
        judge.run(facts_masked={}, narrative=dummy_narrative(), fact_keys=[])

    assert len(tracer.observations) == 3
    expected = {"trace_id": Langfuse.create_trace_id(seed="rid-274-votes")}
    assert [o.start["trace_context"] for o in tracer.observations] == [expected] * 3
    assert {o.start["name"] for o in tracer.observations} == {"judge_v3"}
    assert all(o.merged()["metadata"]["request_id"] == "rid-274-votes" for o in tracer.observations)
    assert all(o.ended == 1 for o in tracer.observations)
