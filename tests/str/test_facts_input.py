"""FactsInput — DraftRequest·SummaryRequest 변환 라운드트립 (SCRUM-129 ★A 1).

핵심: `build_facts(req.to_facts_input(), …)` 가 `build_facts(req, …)` 와 **같은 facts** 를 돌려준다.
초안 녹화 키·facts 가 두 자리에서 어긋나지 않음을 보장.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aml_ai.shared.schemas.str import (
    DraftRequest,
    FactsInput,
    SummaryRequest,
)
from tests.conftest import EXAMPLES, load_json

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def draft_req() -> DraftRequest:
    return DraftRequest.model_validate(load_json(EXAMPLES / "draft_request.json"))


@pytest.fixture
def summary_req() -> SummaryRequest:
    return SummaryRequest.model_validate(load_json(EXAMPLES / "summary_request.json"))


def test_draft_request_to_facts_input_round_trip(draft_req: DraftRequest) -> None:
    """DraftRequest.to_facts_input → 같은 공통 필드."""
    inp = draft_req.to_facts_input()
    assert isinstance(inp, FactsInput)
    assert inp.alert == draft_req.alert
    assert inp.evidence_transaction_ids == draft_req.evidence_transaction_ids
    assert inp.reasons == draft_req.reasons
    assert inp.prior_alert_count == draft_req.prior_alert_count
    assert inp.reporting_institution == draft_req.reporting_institution


def test_summary_request_to_facts_input_round_trip(summary_req: SummaryRequest) -> None:
    """SummaryRequest.to_facts_input → 같은 공통 필드."""
    inp = summary_req.to_facts_input()
    assert isinstance(inp, FactsInput)
    assert inp.alert == summary_req.alert
    assert inp.evidence_transaction_ids == summary_req.evidence_transaction_ids
    assert inp.reasons == summary_req.reasons
    assert inp.prior_alert_count == summary_req.prior_alert_count
    assert inp.reporting_institution == summary_req.reporting_institution


def test_summary_request_schema_matches_draft_shape() -> None:
    """예시 파일로 비교 — draft·summary 가 공통 필드에서 같은 값으로 평가됨."""
    draft = json.loads((EXAMPLES / "draft_request.json").read_text())
    summary = json.loads((EXAMPLES / "summary_request.json").read_text())
    common = ("alert", "evidence_transaction_ids", "reasons", "prior_alert_count", "reporting_institution")
    for k in common:
        assert draft[k] == summary[k], f"{k} 가 예시 draft·summary 에서 다름 — build_facts 공통 입력이 깨짐"


def test_facts_input_requires_reasons_and_prior_alert_count(summary_req: SummaryRequest) -> None:
    """★A 1: reasons·prior_alert_count 는 필수(선택 아님)."""
    from pydantic import ValidationError

    body = summary_req.model_dump(mode="json")
    body.pop("reasons")
    with pytest.raises(ValidationError):
        SummaryRequest.model_validate(body)

    body = summary_req.model_dump(mode="json")
    body.pop("prior_alert_count")
    with pytest.raises(ValidationError):
        SummaryRequest.model_validate(body)


def test_summary_request_reporting_institution_optional(summary_req: SummaryRequest) -> None:
    """reporting_institution 은 선택 — 생략해도 통과."""
    body = summary_req.model_dump(mode="json")
    body.pop("reporting_institution")
    parsed = SummaryRequest.model_validate(body)
    assert parsed.reporting_institution is None
