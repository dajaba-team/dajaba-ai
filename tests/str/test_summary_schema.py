"""SummaryRequest · SummaryOut · SummaryResponse 스키마 — 규약 §6.1, SCRUM-129.

- 요청: evidence·reasons·prior_alert_count 검증 (서비스단 ⊆ 검사는 test_summary_service)
- LLM 출력: 1~6 줄, 한 줄 ≤80자, 81자면 `LlmInvalidOutput`(실제 코드에서는 ValidationError → LlmInvalidOutput 변환)
- 응답: produced_at(SystemTimestamp, UTC Z)·generation_id·case_no·code_checks·generation_meta
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aml_ai.shared.schemas.str import (
    SUMMARY_LINE_MAX,
    SUMMARY_LINES_MAX,
    SummaryOut,
    SummaryRequest,
    SummaryResponse,
)
from tests.conftest import EXAMPLES, load_json


@pytest.fixture
def body() -> dict:
    return load_json(EXAMPLES / "summary_request.json")


# ── SummaryRequest ──


def test_valid_request(body: dict) -> None:
    SummaryRequest.model_validate(body)


def test_request_strict_rejects_unknown_field(body: dict) -> None:
    body["unknown_field"] = 1
    with pytest.raises(ValidationError):
        SummaryRequest.model_validate(body)


def test_request_evidence_min_length(body: dict) -> None:
    body["evidence_transaction_ids"] = []
    with pytest.raises(ValidationError):
        SummaryRequest.model_validate(body)


def test_request_prior_alert_count_ge_0(body: dict) -> None:
    body["prior_alert_count"] = -1
    with pytest.raises(ValidationError):
        SummaryRequest.model_validate(body)


# ── SummaryOut (LLM 출력 스키마) ──


def test_out_valid() -> None:
    SummaryOut(summary_lines=["한 줄 요약"], model_focus=None)
    SummaryOut(summary_lines=["줄1", "줄2"], model_focus="signal_name")


def test_out_zero_lines_rejected() -> None:
    with pytest.raises(ValidationError):
        SummaryOut.model_validate({"summary_lines": [], "model_focus": None})


def test_out_seven_lines_rejected() -> None:
    with pytest.raises(ValidationError):
        SummaryOut.model_validate({"summary_lines": [f"줄{i}" for i in range(SUMMARY_LINES_MAX + 1)]})


def test_out_line_80_chars_ok() -> None:
    line = "가" * SUMMARY_LINE_MAX
    SummaryOut(summary_lines=[line], model_focus=None)


def test_out_line_81_chars_rejected() -> None:
    line = "가" * (SUMMARY_LINE_MAX + 1)
    with pytest.raises(ValidationError):
        SummaryOut(summary_lines=[line], model_focus=None)


def test_out_model_focus_null_allowed() -> None:
    SummaryOut(summary_lines=["줄1"], model_focus=None)


# ── SummaryResponse ──


def test_response_from_example() -> None:
    SummaryResponse.model_validate(load_json(EXAMPLES / "summary_response.json"))


def test_response_produced_at_utc_z_required() -> None:
    """SystemTimestamp — UTC Z, naive 거부(SCRUM-52 와 같음)."""
    body = load_json(EXAMPLES / "summary_response.json")
    body["produced_at"] = "2026-11-06T05:20:00"  # Z 없음
    with pytest.raises(ValidationError):
        SummaryResponse.model_validate(body)
