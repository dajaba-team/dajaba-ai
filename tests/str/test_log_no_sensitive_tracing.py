"""SCRUM-274 — 추적을 켠(가짜 tracer) 상태에서도 초안·검증 stdout 로그에 민감 값이 없다 (docs/shared/04 "추적").

녹화 재생 클라이언트는 원래 안 감싸므로(실제 호출 아님) 이 테스트만 `make_llm_client` 를 바꿔
`TracedLlmClient(RecordedLlmClient, 가짜 tracer)` 로 돌린다. tracer 는 받은 본문을 쌓고(Langfuse 안에만)
`end` 에서 예외를 던져 `tracing_error` 경고 경로까지 탄다 — 그 줄에도 본문·계좌·금액이 없어야 한다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.infrastructure.llm_client import RecordedLlmClient
from aml_ai.shared.infrastructure.tracing import TracedLlmClient
from aml_ai.shared.schemas.str import VerifyResponse, VerifyStatus
from aml_ai.str.application import draft_service, verify_service
from tests.log_support import by_msg, parse_lines, stdout_json_logging
from tests.shared.tracing_support import FakeTracer, _reset_tracing  # noqa: F401 — autouse
from tests.str.log_sensitive_support import TEXT_PROBE_LEN, fixed_values, leaked, narrative_values
from tests.str.verify_integration_support import INTERNAL_KEY, create_draft, verify_body

pytestmark = pytest.mark.db

HEADERS = {"X-Internal-Key": INTERNAL_KEY}


def _traced_bodies(tracer: FakeTracer) -> list[str]:
    """tracer 로 간 프롬프트·출력 본문 — 로그에는 하나도 없어야 한다."""
    values: list[str] = []
    for obs in tracer.observations:
        prompt = obs.start.get("input") or {}
        for text in (prompt.get("system", ""), prompt.get("user", ""), obs.merged().get("output") or ""):
            values += [text, text[:TEXT_PROBE_LEN]]
    return values


def test_traced_draft_verify_logs_have_no_sensitive_values(
    integration_client: TestClient,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tracer = FakeTracer(raise_on_end=RuntimeError("tracer down"))

    def traced(settings: Settings) -> TracedLlmClient:
        inner = RecordedLlmClient(settings.recorded_dir)
        return TracedLlmClient(inner, tracer, server_version=settings.server_version)

    monkeypatch.setattr(draft_service, "make_llm_client", traced)
    monkeypatch.setattr(verify_service, "make_llm_client", traced)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v2")  # v2 초안 → judge_v3 녹화 재생(LLM 호출 있는 경로)
    get_settings.cache_clear()

    with stdout_json_logging():
        draft = create_draft(integration_client, draft_request_sample, "DRF-LOG274-TR")
        vres = integration_client.post("/v1/str/verify", json=verify_body(draft), headers=HEADERS)
    out = capsys.readouterr().out
    lines = parse_lines(out)

    assert VerifyResponse.model_validate(vres.json()).status is VerifyStatus.PASSED  # 결과 그대로
    assert tracer.observations, "추적이 한 번도 안 불림 — 테스트가 헛돎"
    assert any((o.start.get("input") or {}).get("user") for o in tracer.observations)  # 본문은 tracer 로
    assert by_msg(lines, "tracing_error"), "기록 실패 경고 경로를 안 탐"
    assert leaked(out, fixed_values() + narrative_values(draft) + _traced_bodies(tracer)) == []
