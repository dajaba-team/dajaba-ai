"""SCRUM-310 `POST /v1/references/str` 라우터 — 동기 def · 입력 400(서비스 0) · 꺼짐 200 SKIPPED·DISABLED(DB·임베딩 0)."""

from __future__ import annotations

import inspect
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from aml_ai.main import app
from aml_ai.shared.config import get_settings
from aml_ai.str.api import router as router_mod
from tests.conftest import ROOT
from tests.str.str_index_support import Embed, Repo, body, svc

KEY = "test-str-index-key"
URL = "/v1/references/str"


def _client(monkeypatch: pytest.MonkeyPatch, *, enabled: bool) -> TestClient:
    monkeypatch.setenv("AI_INTERNAL_KEY", KEY)
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("STR_INDEX_ENABLED", str(enabled).lower())
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embed")
    monkeypatch.setenv("CORPUS_DIR", str(ROOT / "corpus"))
    get_settings.cache_clear()
    return TestClient(app)


def _use(monkeypatch: pytest.MonkeyPatch, repo: Repo, embed: Embed, **env) -> None:  # noqa: ANN003
    monkeypatch.setitem(
        app.dependency_overrides, router_mod._str_index_service, lambda: svc(repo, embed, **env)
    )  # noqa: SLF001


def test_endpoint_is_sync_def() -> None:
    assert not inspect.iscoroutinefunction(router_mod.index_approved_str)


def test_indexed_200(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, embed = Repo(), Embed()
    _use(monkeypatch, repo, embed)
    with _client(monkeypatch, enabled=True) as c:
        r = c.post(URL, headers={"X-Internal-Key": KEY}, json=body())
    assert r.status_code == HTTPStatus.OK and r.json()["status"] == "INDEXED" and r.json()["chunk_count"] == 4
    get_settings.cache_clear()


def test_disabled_200_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    repo, embed = Repo(), Embed()
    _use(monkeypatch, repo, embed, STR_INDEX_ENABLED=False)
    with _client(monkeypatch, enabled=False) as c:
        r = c.post(URL, headers={"X-Internal-Key": KEY}, json=body())
    assert (
        r.status_code == HTTPStatus.OK
        and r.json()["skip_reason"] == "DISABLED"
        and r.json()["chunk_count"] == 0
    )
    assert embed.calls == [] and repo.reads == 0
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "patch",
    [
        {"sections": [{"section": "SUBJECT", "text": "가" * 20}, {"section": "WHO", "text": "나" * 20}]},
        {"report_no": "STR-1"},
        {"sections": []},
    ],
)
def test_bad_shape_400_without_service(monkeypatch: pytest.MonkeyPatch, patch: dict) -> None:
    repo, embed = Repo(), Embed()
    _use(monkeypatch, repo, embed)
    with _client(monkeypatch, enabled=True) as c:
        r = c.post(URL, headers={"X-Internal-Key": KEY}, json=body(**patch))
    assert r.status_code == HTTPStatus.BAD_REQUEST and r.json()["code"] == "INVALID_REQUEST"
    assert embed.calls == [] and repo.reads == 0
    get_settings.cache_clear()


def test_needs_internal_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, enabled=True) as c:
        r = c.post(URL, json=body())
    assert r.status_code == HTTPStatus.UNAUTHORIZED
    get_settings.cache_clear()
