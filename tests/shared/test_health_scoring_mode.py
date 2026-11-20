"""채점 준비 상태와 STR 기동 상태는 독립이다."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from aml_ai import main
from aml_ai.main import app
from aml_ai.scoring.infrastructure import aml_ml_adapter as adapter
from aml_ai.shared import versioning
from aml_ai.shared.config import Settings, get_settings
from tests.conftest import EXAMPLES, load_json

EXISTING_KEYS = {
    "status",
    "db",
    "llm",
    "server_version",
    "model_version",
    "feature_version",
    "retrieval_version",
}


@pytest.fixture()
def health(monkeypatch: pytest.MonkeyPatch) -> Iterator:
    monkeypatch.delenv("AI_SCORING_MOCK", raising=False)
    monkeypatch.setattr(versioning, "_served_model", None)
    monkeypatch.setattr(main, "db_ping", lambda _: "ok")

    def call(**overrides: object) -> tuple[int, dict]:
        settings = Settings(_env_file=None, **overrides)  # type: ignore[arg-type]
        app.dependency_overrides[get_settings] = lambda: settings
        with TestClient(app) as client:
            response = client.get("/v1/health")
        return response.status_code, response.json()

    yield call
    app.dependency_overrides.pop(get_settings, None)


def test_default_settings_is_mock(health) -> None:
    code, body = health()
    assert code == 200
    assert body["scoring_mode"] == "mock"
    assert body["status"] == "ok"


def test_health_does_not_try_to_load_model(health, monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_import(name: str) -> None:
        pytest.fail(f"health tried to import {name}")

    monkeypatch.setattr(adapter, "import_module", unexpected_import)
    code, body = health(AI_SCORING_MOCK=False)
    assert code == 200
    assert body["scoring_mode"] == "unavailable"
    assert body["status"] == "ok"
    assert body["model_version"] is None and body["feature_version"] is None


def test_health_reports_served_model(health) -> None:
    versioning.set_served_model(("saved-model", "saved-features"))
    code, body = health(AI_SCORING_MOCK=False)
    assert code == 200
    assert body["scoring_mode"] == "model"
    assert body["model_version"] == "saved-model"
    assert body["feature_version"] == "saved-features"


def test_model_load_failure_does_not_prevent_str_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    attempted = False

    def broken_model(name: str) -> None:
        nonlocal attempted
        assert name == "aml_ml"
        attempted = True
        raise RuntimeError("invalid model artifact")

    monkeypatch.setattr(adapter, "import_module", broken_model)
    monkeypatch.setattr(versioning, "_served_model", ("prior-model", "prior-features"))
    monkeypatch.setattr(main, "db_ping", lambda _: "ok")
    monkeypatch.setenv("AI_SCORING_MOCK", "false")
    monkeypatch.setenv("AI_SCORING_HISTORY_START", "2022-09-01T00:00:00")
    monkeypatch.setenv("AI_SCORING_HISTORY_END", "2022-09-11T00:00:00")
    with TestClient(app) as client:
        assert client.get("/v1/health").json()["scoring_mode"] == "model"
        response = client.post(
            "/v1/scores",
            headers={"X-Internal-Key": "test-key"},
            json=load_json(EXAMPLES / "score_request.json"),
        )
        assert response.status_code == 503
        assert response.json()["code"] == "MODEL_UNAVAILABLE"
        assert attempted
        health_body = client.get("/v1/health").json()
        assert health_body["status"] == "ok"
        assert health_body["scoring_mode"] == "unavailable"
        assert "/v1/str/drafts" in client.get("/openapi.json").json()["paths"]


def test_existing_keys_unchanged_and_no_auth(health) -> None:
    code, body = health()
    assert code == 200
    assert set(body) == EXISTING_KEYS | {"scoring_mode"}
    assert body["llm"] in {"ok", "missing_key"}
    assert body["db"] == "ok" or body["db"].startswith("down:")
