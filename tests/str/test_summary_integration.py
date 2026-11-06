"""`/v1/cases/summary` 녹화 통합 테스트 (SCRUM-129).

흐름 — HTTP → SummaryService → ops 읽기 → facts → end_read(SCRUM-122) → RecordedLlmClient
→ run_summary_code_checks → generations 저장(kind=SUMMARY) → 응답.
`AI_LLM_MOCK=true` · `RAG_ENABLED=false`. 녹화 파일(`recorded/summary_v1/<key>.json`) 필요.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import SummaryResponse
from tests.str.integration_support import INTEGRATION_INTERNAL_KEY

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
INTERNAL_KEY = INTEGRATION_INTERNAL_KEY


def _fan_in_body(sample: dict, *, case_no: str = "CASE-SCRUM129-01") -> dict:
    """ops_seed 가 가정하는 요청 모양 — draft 통합 테스트와 같은 숫자."""
    body = {**sample}
    body["case_no"] = case_no
    body["alert"] = {
        **body["alert"],
        "account_key": "010_8000EBD30",
        "entity_id": "80062E240",
        "transaction_ids": [1, 2, 3],
    }
    body["evidence_transaction_ids"] = [1, 2, 3]
    return body


@pytest.fixture
def summary_request_sample() -> dict:
    return json.loads((REPO_ROOT / "contracts" / "examples" / "summary_request.json").read_text())


def test_summary_success_through_recorded_llm(
    integration_client: TestClient,
    db_session: Session,
    summary_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """200 + summary_lines 1~6 + code_checks 전부 match + generations.kind=SUMMARY/SUCCEEDED."""
    get_settings.cache_clear()
    body = _fan_in_body(summary_request_sample, case_no="CASE-OK-01")
    res = integration_client.post("/v1/cases/summary", json=body, headers={"X-Internal-Key": INTERNAL_KEY})
    assert res.status_code == 200, res.text
    out = SummaryResponse.model_validate(res.json())
    assert 1 <= len(out.summary_lines) <= 6
    assert all(c.match for c in out.code_checks)
    assert out.generation_meta.prompt_version == "summary_v1"
    row = db_session.execute(
        text(
            "SELECT kind, status, case_no, draft_id FROM ai.generations WHERE case_no=:c AND kind='SUMMARY'"
        ),
        {"c": body["case_no"]},
    ).one()
    assert row.kind == "SUMMARY"
    assert row.status == "SUCCEEDED"
    assert row.case_no == body["case_no"]
    assert row.draft_id is None


def test_summary_evidence_not_subset_rejected(
    integration_client: TestClient,
    summary_request_sample: dict,
) -> None:
    """evidence_transaction_ids ⊄ alert.transaction_ids → 400 INVALID_REQUEST."""
    body = _fan_in_body(summary_request_sample, case_no="CASE-BAD-01")
    body["evidence_transaction_ids"] = [9999]  # alert.transaction_ids 밖
    res = integration_client.post("/v1/cases/summary", json=body, headers={"X-Internal-Key": INTERNAL_KEY})
    assert res.status_code == 400, res.text
    assert res.json()["code"] == "INVALID_REQUEST"
