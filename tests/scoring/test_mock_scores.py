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
    assert body["scores"][0]["alert_id"] == 1001
    assert 0 <= body["scores"][0]["score"] <= 1
    assert body["scoring_meta"]["model_version"] == "mock-0"
