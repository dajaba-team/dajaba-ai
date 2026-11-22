"""SCRUM-309 추가 검토 3 회귀 — 하이픈 변형·나뉜 계좌 가리기 · 응답 시작 직전 마감(임베딩·저장소 마감은 `_budget`)."""

from __future__ import annotations

import asyncio
import re
import time
from http import HTTPStatus

import pytest
from fastapi import routing as fastapi_routing
from fastapi.testclient import TestClient

from aml_ai.main import app
from aml_ai.shared.config import get_settings
from aml_ai.shared.received_at import RESPONSE_DEADLINE, ResponseDeadlineGuard
from aml_ai.str.api import router as router_mod
from aml_ai.str.application import reference_search_service as svc_mod
from aml_ai.str.domain.reference_search import masked_query
from tests.conftest import ROOT
from tests.str.test_reference_search import _Embed, _hit, _Repo, _req, _svc

_SEPS = r"[-.\s‐-―−﹘﹣－]"


@pytest.mark.parametrize(
    ("raw", "joined", "tail"),
    [
        ("1234–5678–9012", "123456789012", "****9012"),  # en dash
        ("1234—5678—9012", "123456789012", "****9012"),  # em dash
        ("1234－5678－9012", "123456789012", "****9012"),  # 전각
        ("1234−5678−9012", "123456789012", "****9012"),  # 빼기 기호
        ("1234‐5678‑9012", "123456789012", "****9012"),  # 하이픈·줄바꿈 없는 하이픈
        ("8000-EBD-30", "8000EBD30", "****BD30"),
        ("8000 ebd 30", "8000ebd30", "****bd30"),
        ("10_123456-78", "12345678", "10_****5678"),
        ("10_8000-EBD-30", "8000EBD30", "10_****BD30"),
        ("10_1234 – 5678", "12345678", "10_****5678"),
    ],
)
def test_split_accounts_hidden_in_embedder_input(raw: str, joined: str, tail: str) -> None:
    sent = _Embed()
    _svc(sent, _Repo()).search(_req(query=f"계좌 {raw} 로 돌아옴"), None)
    final = sent.texts[0]
    assert joined not in re.sub(_SEPS, "", final) and tail in final  # 구분자 빼고 이어도 원문 0, 끝 4자리만


@pytest.mark.parametrize("word", ["ADD-BEEF", "CAFE BABE", "DEAD-BEEF 3회"])
def test_hex_words_without_digits_kept(word: str) -> None:
    assert masked_query(word) == word


def test_short_numbers_and_amounts_kept() -> None:
    assert masked_query("3회 송금 15,000,000원 A-1") == "3회 송금 15,000,000원 A-1"


# --- H2 응답 경계 -----------------------------------------------------------------------------


def _client(monkeypatch: pytest.MonkeyPatch, embed: _Embed, repo: _Repo) -> TestClient:
    monkeypatch.setenv("AI_INTERNAL_KEY", "k")
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("RAG_REFERENCE_SEARCH_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embed")
    monkeypatch.setenv("CORPUS_DIR", str(ROOT / "corpus"))
    get_settings.cache_clear()
    monkeypatch.setitem(
        app.dependency_overrides, router_mod._reference_search_service, lambda: _svc(embed, repo)
    )  # noqa: SLF001
    return TestClient(app)


def _post(c: TestClient, budget: str):  # noqa: ANN202
    return c.post(
        "/v1/references/search",
        headers={"X-Internal-Key": "k", "X-Budget-Ms": budget, "X-Request-Id": "rid-309"},
        json={"typologies": ["CYCLE"]},
    )


def test_slow_success_log_is_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc_mod.log, "info", lambda *a, **kw: time.sleep(0.15))
    with _client(monkeypatch, _Embed(), _Repo([_hit("c", "A", 0.5)])) as c:
        r = _post(c, "100")
    assert r.status_code == HTTPStatus.BAD_GATEWAY and r.json()["code"] == "LLM_UNAVAILABLE"
    assert r.json()["request_id"] == "rid-309" and r.headers["x-request-id"] == "rid-309"
    get_settings.cache_clear()


def test_slow_response_validation_is_502(monkeypatch: pytest.MonkeyPatch) -> None:
    real = fastapi_routing.serialize_response

    async def slow(*a, **kw):  # noqa: ANN002, ANN003, ANN202 — 응답 검증 대기 흉내
        await asyncio.sleep(0.15)
        return await real(*a, **kw)

    monkeypatch.setattr(fastapi_routing, "serialize_response", slow)
    with _client(monkeypatch, _Embed(), _Repo([_hit("c", "A", 0.5)])) as c:
        r = _post(c, "100")
    assert r.status_code == HTTPStatus.BAD_GATEWAY and r.json()["code"] == "LLM_UNAVAILABLE"
    get_settings.cache_clear()


def test_in_budget_is_200(monkeypatch: pytest.MonkeyPatch) -> None:
    with _client(monkeypatch, _Embed(), _Repo([_hit("c", "A", 0.5)])) as c:
        r = _post(c, "4000")
    assert r.status_code == HTTPStatus.OK and r.json()["status"] == "FOUND"
    get_settings.cache_clear()


def _asgi(path: str, deadline: float) -> list[dict]:
    async def inner(scope, receive, send):  # noqa: ANN001, ANN202
        scope["state"][RESPONSE_DEADLINE] = deadline
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    sent: list[dict] = []

    async def send(m: dict) -> None:
        sent.append(m)

    guard = ResponseDeadlineGuard(inner, paths=("/v1/references/search",))
    asyncio.run(guard({"type": "http", "path": path, "state": {}}, None, send))
    return sent


def test_guard_only_on_search_path() -> None:
    past = time.monotonic() - 1
    assert _asgi("/v1/str/ask", past)[0]["status"] == HTTPStatus.OK  # 다른 경로는 안 걸림
    out = _asgi("/v1/references/search", past)
    assert (
        out[0]["status"] == HTTPStatus.BAD_GATEWAY and len(out) == 2 and b"LLM_UNAVAILABLE" in out[1]["body"]
    )
    assert _asgi("/v1/references/search", time.monotonic() + 5)[0]["status"] == HTTPStatus.OK
