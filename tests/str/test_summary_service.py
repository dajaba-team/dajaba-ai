"""SummaryService — 서비스 단위 (SCRUM-129, 08_testing "요약" 줄).

시나리오 7 — 08_testing 매핑 그대로.
"""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.errors import LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.schemas.str import SummaryRequest
from tests.conftest import EXAMPLES, load_json
from tests.str.summary_service_support import (
    StubLlm,
    bad_amount_text,
    build_service,
    ok_text,
)


@pytest.fixture(autouse=True)
def _clear() -> None:
    get_settings.cache_clear()


@pytest.fixture
def req() -> SummaryRequest:
    return SummaryRequest.model_validate(load_json(EXAMPLES / "summary_request.json"))


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """StubReader 를 쓰기에 end_read(None) 은 no-op 로."""
    import aml_ai.str.application.summary_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def test_ok_returns_200_with_matches(req: SummaryRequest) -> None:
    """정상 — LLM 응답 1회 + code_checks 전부 match + prompt_version=summary_v1."""
    stub = StubLlm(responses=[ok_text()])
    out = build_service(stub).summarize(req)
    assert 1 <= len(out.summary_lines) <= 6
    assert all(c.match for c in out.code_checks)
    assert out.generation_meta.prompt_version == "summary_v1"
    assert out.case_no == req.case_no
    assert out.generation_id.startswith("g-")
    assert len(stub.calls) == 1


def test_schema_failure_then_success_regen(req: SummaryRequest) -> None:
    """LLM 1차 스키마 실패 → 2차 성공 — 생성기 안 재생성 1회."""
    stub = StubLlm(responses=["not-json-at-all", ok_text()])
    out = build_service(stub).summarize(req)
    assert len(stub.calls) == 2
    assert all(c.match for c in out.code_checks)


def test_schema_failure_twice_raises_invalid_output(req: SummaryRequest) -> None:
    """LLM 두 번 다 스키마 실패 → LlmInvalidOutput."""
    stub = StubLlm(responses=["not-json", "also-not-json"])
    with pytest.raises(LlmInvalidOutput):
        build_service(stub).summarize(req)
    assert len(stub.calls) == 2


def test_schema_failure_message_does_not_leak_llm_body(req: SummaryRequest) -> None:
    """★ 리뷰 high — LlmInvalidOutput message 에 LLM 응답 본문이 섞이면 안 됨.

    Pydantic ValidationError 가 input_value 로 LLM 원문을 포함. f-string 으로 붙이면
    HTTP 502 message 로 유출. 고정 문구만.
    """
    leaky_body = "42750.50 USD leak-marker"
    stub = StubLlm(responses=[leaky_body, leaky_body])
    with pytest.raises(LlmInvalidOutput) as exc_info:
        build_service(stub).summarize(req)
    assert "leak-marker" not in str(exc_info.value)
    assert "42750.50" not in str(exc_info.value)


def test_code_failure_then_regen_success(req: SummaryRequest) -> None:
    """코드 실패 → 서비스가 재생성 1회 → 성공 (clock 고정으로 예산 보장)."""
    stub = StubLlm(responses=[bad_amount_text(), ok_text()])
    out = build_service(stub, clock=lambda: 0.0).summarize(req)
    assert len(stub.calls) == 2
    assert all(c.match for c in out.code_checks)


def test_code_failure_regen_with_realistic_clock(req: SummaryRequest) -> None:
    """★ 리뷰 medium — 첫 호출이 6초 걸리는 현실적 시계에서도 재생성 돎.

    기본 summary_budget_s=40, summary_regen_min_remaining_s=15, summary_llm_timeout_s=15 —
    첫 호출 6초 뒤 남은 34초가 15초 이상이라 재생성 분기 진입. 리뷰 전에는 regen_min_remaining_s=40
    을 재사용해 분기가 막혔음.
    """
    stub = StubLlm(responses=[bad_amount_text(), ok_text()])
    ticks = iter(
        [0.0, 0.0, 6.0, 6.0, 6.0]
    )  # 서비스 deadline 계산→1차 preflight→1차 끝→재생성 판정→2차 preflight
    out = build_service(stub, clock=lambda: next(ticks)).summarize(req)
    assert len(stub.calls) == 2
    assert all(c.match for c in out.code_checks)


def test_code_failure_remaining_14s_no_second_call(req: SummaryRequest) -> None:
    """★ 커밋 전 수정 — 남은 14초(summary_llm_timeout_s=15 미만)면 2차 호출 안 함.

    첫 호출 뒤 남은 시간이 LLM 1회 제한보다 작으면 _can_regenerate 가 False → 재생성 스킵.
    "남은 시간 < 호출 1회 제한이면 안 부름" 불변식 유지. 응답은 200 + code_checks.match=false.
    """
    stub = StubLlm(responses=[bad_amount_text(), ok_text()])
    # deadline = 0 + 40 = 40. 1차 뒤 clock=26 → 남은 14 < 15 → 재생성 안 함.
    ticks = iter([0.0, 0.0, 26.0, 26.0, 26.0])
    out = build_service(stub, clock=lambda: next(ticks)).summarize(req)
    assert len(stub.calls) == 1  # 재생성 안 돎
    assert any(not c.match for c in out.code_checks)


def test_code_failure_twice_returns_200_with_match_false(req: SummaryRequest) -> None:
    """★A 3 — 두 번 다 코드 실패여도 200 + code_checks.match=false 담아 반환."""
    stub = StubLlm(responses=[bad_amount_text(), bad_amount_text()])
    out = build_service(stub, clock=lambda: 0.0).summarize(req)
    assert len(stub.calls) == 2
    assert any(not c.match for c in out.code_checks)
    assert out.generation_meta.prompt_version == "summary_v1"


def test_budget_exceeded_raises_unavailable(req: SummaryRequest) -> None:
    """예산 초과 → LlmUnavailable (초안과 같은 규칙)."""
    stub = StubLlm(responses=[ok_text()])
    big_jump = iter([0.0, 10_000.0, 10_000.0, 10_000.0])
    with pytest.raises(LlmUnavailable):
        build_service(stub, clock=lambda: next(big_jump)).summarize(req)


def test_model_focus_rejected_when_outside_signal_has_digit(
    req: SummaryRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """model_focus 에 '3건' 같은 관측 수치가 섞이면 응답 null + 경고 로그 1회."""
    payload = json.loads(ok_text())
    payload["model_focus"] = "account_in_counterparties_24h 가 3건 집중"
    stub = StubLlm(responses=[json.dumps(payload, ensure_ascii=False)])

    import aml_ai.str.application.summary_service as mod

    calls: list[tuple[str, dict]] = []

    class _Spy:
        def warning(self, msg, extra=None):
            calls.append((msg, dict(extra or {})))

    monkeypatch.setattr(mod, "log", _Spy())
    out = build_service(stub).summarize(req)
    assert out.model_focus is None
    assert ("summary_model_focus_rejected", {"reason": "non_signal_digit"}) in calls
