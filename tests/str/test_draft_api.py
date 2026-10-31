"""STR 요청 시각 검증은 기존 INVALID_REQUEST 응답 계약을 따른다."""

from datetime import datetime
from http import HTTPStatus
from unittest.mock import Mock

import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient
from pydantic import ValidationError

from aml_ai.main import app
from aml_ai.shared.schemas.str import DraftRequest
from aml_ai.str.api.router import _draft_service
from aml_ai.str.application.draft_service import DraftService
from tests.conftest import EXAMPLES, load_json


def test_draft_request_rejects_naive_datetime() -> None:
    req = load_json(EXAMPLES / "draft_request.json")
    req["alert"]["created_at"] = datetime.fromisoformat(req["alert"]["created_at"]).replace(tzinfo=None)
    assert req["alert"]["created_at"].tzinfo is None

    with pytest.raises(ValidationError) as exc:
        DraftRequest.model_validate(req)

    assert [(error["loc"], error["type"]) for error in exc.value.errors()] == [
        (("alert", "created_at"), "timezone_aware")
    ]


def test_drafts_reject_naive_datetime_as_invalid_request(monkeypatch: pytest.MonkeyPatch) -> None:
    req = load_json(EXAMPLES / "draft_request.json")
    req["alert"]["created_at"] = datetime.fromisoformat(req["alert"]["created_at"]).replace(tzinfo=None)
    service = Mock(spec=DraftService)
    monkeypatch.setitem(app.dependency_overrides, _draft_service, lambda: service)

    with TestClient(app) as client:
        response = client.post(
            "/v1/str/drafts",
            headers={"X-Internal-Key": "test-key"},
            json=jsonable_encoder(req),
        )

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["code"] == "INVALID_REQUEST"
    assert "alert.created_at" in response.json()["message"]
    service.create.assert_not_called()
