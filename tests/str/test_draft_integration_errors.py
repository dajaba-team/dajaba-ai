"""`/v1/str/drafts` 통합 실패 흐름 (SCRUM-20).

4종 — 없는 거래 ID 400, 같은 draft_id 다른 본문 400, 녹화 키 miss 502 + generations FAILED, 키 없음 401.
정상·경계는 `test_draft_integration.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from aml_ai.shared.config import get_settings
from tests.str.test_draft_integration import INTERNAL_KEY, _fan_in_body

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


def test_unknown_transaction_id_returns_400(
    integration_client: TestClient,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v1")
    get_settings.cache_clear()
    body = _fan_in_body(draft_request_sample, draft_id="DRF-UNKNOWN-TX")
    body["alert"]["transaction_ids"] = [9_999_999]
    body["evidence_transaction_ids"] = [9_999_999]
    res = integration_client.post("/v1/str/drafts", json=body, headers={"X-Internal-Key": INTERNAL_KEY})
    assert res.status_code == 400
    assert res.json()["code"] == "INVALID_REQUEST"


def test_same_draft_different_body_returns_400(
    integration_client: TestClient,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v1")
    get_settings.cache_clear()
    first_body = _fan_in_body(draft_request_sample, draft_id="DRF-HASH-CLASH")
    second_body = _fan_in_body(draft_request_sample, draft_id="DRF-HASH-CLASH")
    second_body["case_no"] = first_body["case_no"] + "-x"  # 해시가 달라짐
    first = integration_client.post(
        "/v1/str/drafts", json=first_body, headers={"X-Internal-Key": INTERNAL_KEY}
    )
    assert first.status_code == 200
    second = integration_client.post(
        "/v1/str/drafts", json=second_body, headers={"X-Internal-Key": INTERNAL_KEY}
    )
    assert second.status_code == 400
    assert second.json()["code"] == "INVALID_REQUEST"


def test_recording_miss_returns_502_and_marks_failed(
    integration_client: TestClient,
    db_session: Session,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """investigator_notes 를 바꿔 user 프롬프트 바뀌면 녹화 키 miss → 502 + generations FAILED."""
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v1")
    get_settings.cache_clear()
    body = _fan_in_body(draft_request_sample, draft_id="DRF-MISS-01", notes_extra="RECORDING_MISS_SENTINEL")
    res = integration_client.post("/v1/str/drafts", json=body, headers={"X-Internal-Key": INTERNAL_KEY})
    assert res.status_code == 502
    assert res.json()["code"] == "LLM_UNAVAILABLE"
    row = db_session.execute(
        text("SELECT status, error FROM ai.generations WHERE draft_id=:d"),
        {"d": body["draft_id"]},
    ).one()
    assert row.status == "FAILED"
    assert "LLM_UNAVAILABLE" in (row.error or "")


def test_missing_internal_key_returns_401(
    integration_client: TestClient,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v1")
    get_settings.cache_clear()
    body = _fan_in_body(draft_request_sample, draft_id="DRF-NO-KEY")
    res = integration_client.post("/v1/str/drafts", json=body)  # 헤더 없음
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHENTICATED"
