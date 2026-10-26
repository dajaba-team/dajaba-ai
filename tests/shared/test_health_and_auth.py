from __future__ import annotations

from fastapi.testclient import TestClient

from aml_ai.main import app


def test_health_no_auth() -> None:
    with TestClient(app) as c:
        r = c.get("/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "server_version" in body and "X-Request-Id" in r.headers


def test_internal_key_required() -> None:
    with TestClient(app) as c:
        r = c.post("/v1/scores", json={"batch_run_id": 1, "alerts": []})
    assert r.status_code == 401
    assert r.json()["code"] == "UNAUTHENTICATED"
    assert r.json()["request_id"]


def test_request_id_passthrough() -> None:
    with TestClient(app) as c:
        r = c.get("/v1/health", headers={"X-Request-Id": "abc123"})
    assert r.headers["X-Request-Id"] == "abc123"


def test_validation_error_is_contract_shape() -> None:
    with TestClient(app) as c:
        r = c.post(
            "/v1/scores", headers={"X-Internal-Key": "test-key"}, json={"batch_run_id": 1, "alerts": []}
        )
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_REQUEST"
