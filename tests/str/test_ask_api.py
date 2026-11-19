"""`POST /v1/cases/ask` 라우터 — 동기 def · 요청 검증 400 · 상태 4종 200 (SCRUM-290 2/2, 03)."""

from __future__ import annotations

import inspect
from http import HTTPStatus
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import AskResponse
from aml_ai.str.api import router as router_mod
from aml_ai.str.application.ask_service import AskService
from tests.conftest import EXAMPLES, load_json

KEY = "test-ask-key"
STATES = ["answered", "no_data", "unverified", "out_of_scope"]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AI_INTERNAL_KEY", KEY)
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_ask_endpoint_is_sync_def() -> None:
    """이벤트 루프 스레드에서 호출 전체 마감 경로를 부르면 500 — 동기 def 로 둔다(SCRUM-322)."""
    assert not inspect.iscoroutinefunction(router_mod.ask_case)


@pytest.mark.parametrize("state", STATES)
def test_ask_returns_200_for_each_state(state: str, client: TestClient, monkeypatch) -> None:
    res_body = load_json(EXAMPLES / f"ask_response_{state}.json")
    service = Mock(spec=AskService)
    service.ask.return_value = AskResponse.model_validate(res_body)
    monkeypatch.setitem(app.dependency_overrides, router_mod._ask_service, lambda: service)
    response = client.post(
        "/v1/cases/ask", headers={"X-Internal-Key": KEY}, json=load_json(EXAMPLES / "ask_request.json")
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == res_body["status"]
    service.ask.assert_called_once()


@pytest.mark.parametrize("question", ["", "   ", "가" * 301])
def test_ask_bad_question_is_400_without_service(question: str, client: TestClient, monkeypatch) -> None:
    service = Mock(spec=AskService)
    monkeypatch.setitem(app.dependency_overrides, router_mod._ask_service, lambda: service)
    body = {**load_json(EXAMPLES / "ask_request.json"), "question": question}
    response = client.post("/v1/cases/ask", headers={"X-Internal-Key": KEY}, json=body)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["code"] == "INVALID_REQUEST"
    service.ask.assert_not_called()
