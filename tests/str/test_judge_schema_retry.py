"""SCRUM-147 추가 검토 — 초안용 Judge(schema_retry=0) 은 스키마 실패해도 1번만 호출.

verify 경로(기본 1회)는 `test_judge_retry.py` 가 그대로 커버한다.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.errors import LlmInvalidOutput
from tests.str.judge_support import StubCall, StubLlm, generous_deadline, judge_payload, make_judge


def test_judge_schema_retry_zero_single_call_only() -> None:
    stub = StubLlm(call_specs=[StubCall(text="not-json"), StubCall(text=judge_payload([4, 5, 4, 4, 5]))])
    with pytest.raises(LlmInvalidOutput):
        make_judge(stub, schema_retry=0).run({"facts": "masked"}, [], deadline=generous_deadline())
    assert len(stub.calls) == 1  # 재시도 없음
