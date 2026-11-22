"""SCRUM-309 `POST /v1/references/search` 라우터 — 스위치·입력·헤더 400(서비스·DB·임베딩 0) · 정상 200 (str/03)."""

from __future__ import annotations

import inspect
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import ReferenceSearchResponse
from aml_ai.str.api import router as router_mod
from tests.conftest import EXAMPLES, ROOT, load_json

KEY = "test-ref-key"
URL = "/v1/references/search"
BODY = {
    "typologies": ["CYCLE"],
    "query": "해외 계좌를 거쳐 돌아오는 흐름",
    "top_k": 5,
    "source_types": ["PUBLIC"],
}


class _Svc:
    def __init__(self) -> None:
        self.calls: list[int | None] = []

    def search(self, req, budget_ms, received_at=None):  # noqa: ANN001, ANN201
        self.calls.append(budget_ms)
        self.received_at = received_at
        return ReferenceSearchResponse.model_validate(
            load_json(EXAMPLES / "reference_search_response_found.json")
        )


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> _Svc:
    s = _Svc()
    monkeypatch.setitem(app.dependency_overrides, router_mod._reference_search_service, lambda: s)  # noqa: SLF001
    return s


def _client(monkeypatch: pytest.MonkeyPatch, *, enabled: bool = True, rag: bool = True) -> TestClient:
    monkeypatch.setenv("AI_INTERNAL_KEY", KEY)
    monkeypatch.setenv("RAG_ENABLED", str(rag).lower())
    monkeypatch.setenv("RAG_REFERENCE_SEARCH_ENABLED", str(enabled).lower())
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embed")  # 개인 .env 없이도 기동 검사 통과(검토 2)
    monkeypatch.setenv("CORPUS_DIR", str(ROOT / "corpus"))
    get_settings.cache_clear()
    return TestClient(app)


def _post(client: TestClient, body: dict, **headers: str):  # noqa: ANN202
    return client.post(URL, headers={"X-Internal-Key": KEY, **headers}, json=body)


def test_endpoint_is_sync_def() -> None:
    assert not inspect.iscoroutinefunction(router_mod.search_references)


def test_ok_returns_example_shape(monkeypatch: pytest.MonkeyPatch, svc: _Svc) -> None:
    with _client(monkeypatch) as c:
        r = _post(c, BODY, **{"X-Budget-Ms": "4000"})
    assert r.status_code == HTTPStatus.OK and r.json()["status"] == "FOUND" and svc.calls == [4000]
    assert all("text" not in item for item in r.json()["results"])  # 본문 칸 0


@pytest.mark.parametrize(("enabled", "rag"), [(False, True), (True, False)])
def test_switch_off_is_400_without_service(
    monkeypatch: pytest.MonkeyPatch, svc: _Svc, enabled: bool, rag: bool
) -> None:
    with _client(monkeypatch, enabled=enabled, rag=rag) as c:
        r = _post(c, BODY)
    assert (
        r.status_code == HTTPStatus.BAD_REQUEST and r.json()["code"] == "INVALID_REQUEST" and svc.calls == []
    )


EMOJI_200 = "😀" * 100  # UTF-16 200
BAD = [
    {"typologies": []},
    {"typologies": ["FAN_IN", "FAN_OUT", "CYCLE", "GATHER_SCATTER"]},
    {"typologies": ["FX_RELAY"]},
    {"typologies": ["NOT_A_TYPE"]},
    {"typologies": ["CYCLE", "CYCLE"]},
    {"query": "가" * 201},
    {"query": EMOJI_200 + "a"},
    {"query": "   "},
    {"query": ""},
    {"top_k": 0},
    {"top_k": 11},
    {"source_types": ["APPROVED_STR"]},
    {"source_types": []},
    {"source_types": ["PUBLIC", "PUBLIC"]},
    {"extra": 1},
]


@pytest.mark.parametrize("change", BAD)
def test_bad_input_is_400_without_service(monkeypatch: pytest.MonkeyPatch, svc: _Svc, change: dict) -> None:
    with _client(monkeypatch) as c:
        r = _post(c, {**BODY, **change})
    assert (
        r.status_code == HTTPStatus.BAD_REQUEST and r.json()["code"] == "INVALID_REQUEST" and svc.calls == []
    )


@pytest.mark.parametrize(
    "change", [{"query": "가" * 200}, {"query": EMOJI_200}, {"query": None}, {"top_k": 10}, {"top_k": 1}]
)
def test_boundaries_pass(monkeypatch: pytest.MonkeyPatch, svc: _Svc, change: dict) -> None:
    body = {k: v for k, v in {**BODY, **change}.items()}
    with _client(monkeypatch) as c:
        r = _post(c, body)
    assert r.status_code == HTTPStatus.OK and len(svc.calls) == 1


def test_defaults(monkeypatch: pytest.MonkeyPatch, svc: _Svc) -> None:
    with _client(monkeypatch) as c:
        r = _post(c, {"typologies": ["FAN_IN"]})
    assert r.status_code == HTTPStatus.OK and svc.calls == [None]


@pytest.mark.parametrize("value", ["abc", "0", "-5", "1.5"])
def test_bad_budget_header_is_400(monkeypatch: pytest.MonkeyPatch, svc: _Svc, value: str) -> None:
    with _client(monkeypatch) as c:
        r = _post(c, BODY, **{"X-Budget-Ms": value})
    assert r.status_code == HTTPStatus.BAD_REQUEST and svc.calls == []
