from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from aml_ai.scoring.application.score_service import ScoreService
from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.errors import DbUnavailable
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
    assert item["failure_code"] is None
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


def test_scores_db_unavailable_is_whole_request_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(self: ScoreService, req: object) -> None:
        raise DbUnavailable("transactions read failed")

    monkeypatch.setattr(ScoreService, "score", _boom)
    with TestClient(app) as c:
        r = c.post(
            "/v1/scores",
            headers={"X-Internal-Key": "test-key"},
            json=load_json(EXAMPLES / "score_request.json"),
        )
    assert r.status_code == 503
    assert r.json()["code"] == "DB_UNAVAILABLE"


@pytest.mark.parametrize(
    ("start", "end", "mock", "reason"),
    [
        ("", "2022-09-11T00:00:00", False, "missing_bound"),
        ("bad", "2022-09-11T00:00:00", False, "invalid_format"),
        ("2022-09-01T00:00:00+00:00", "2022-09-11T00:00:00", False, "invalid_timezone"),
        ("2022-09-11T00:00:00", "2022-09-01T00:00:00", False, "invalid_order"),
        ("bad", "", True, None),
    ],
)
def test_scores_history_config_is_checked_only_in_model_mode(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    start: str,
    end: str,
    mock: bool,
    reason: str | None,
) -> None:
    settings = Settings(
        _env_file=None,
        AI_SCORING_MOCK=mock,
        AI_SCORING_HISTORY_START=start,
        AI_SCORING_HISTORY_END=end,
    )
    monkeypatch.setattr("aml_ai.main.get_settings", lambda: settings)
    monkeypatch.setitem(app.dependency_overrides, get_settings, lambda: settings)

    def unexpected_load() -> None:
        pytest.fail("model loading must not run")

    monkeypatch.setattr("aml_ai.scoring.application.score_service.AmlMlAdapter.load", unexpected_load)
    with TestClient(app) as c:
        r = c.post(
            "/v1/scores",
            headers={"X-Internal-Key": "test-key"},
            json=load_json(EXAMPLES / "score_request.json"),
        )
    if reason is None:
        assert r.status_code == 200
        assert r.json()["scoring_meta"]["model_version"] == "mock-0"
    else:
        assert r.status_code == 503
        assert r.json()["code"] == "MODEL_UNAVAILABLE"
        assert any(getattr(record, "history_config_error", None) == reason for record in caplog.records)
