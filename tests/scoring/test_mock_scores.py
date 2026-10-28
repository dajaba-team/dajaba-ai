from __future__ import annotations

from fastapi.testclient import TestClient

from aml_ai.main import app
from tests.conftest import EXAMPLES, load_json


def test_mock_scores_match_contract() -> None:
    with TestClient(app) as c:
        r = c.post(
            "/v1/scores",
            headers={"X-Internal-Key": "test-key"},
            json=load_json(EXAMPLES / "score_request.json"),
        )
    assert r.status_code == 200
    body = r.json()
    item = body["scores"][0]
    assert item["alert_id"] == "ALT-20220903-000142"
    assert 0 <= item["score"] <= 1
    assert item["data_quality_status"] == "OK"
    assert item["evidence_transaction_ids"] == [104221, 104233, 104301]
    assert body["scoring_meta"]["model_version"] == "mock-0"
    assert body["produced_at"]


def test_scores_reject_numeric_alert_id() -> None:
    req = load_json(EXAMPLES / "score_request.json")
    req["alerts"][0]["alert_id"] = 1001
    with TestClient(app) as c:
        r = c.post("/v1/scores", headers={"X-Internal-Key": "test-key"}, json=req)
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_REQUEST"
