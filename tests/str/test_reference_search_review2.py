"""SCRUM-309 추가 검토 2 회귀 — 연속 구분자 가리기 · 들어온 시각부터 마감 · 반환 직전 마감 · 앱 수명 루프(DNS 지연) · 연결 뒤 남은 시간."""

from __future__ import annotations

import re
import socket
import time
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from aml_ai.main import app
from aml_ai.shared.config import Settings, get_settings
from aml_ai.shared.errors import LlmUnavailable
from aml_ai.str.api import router as router_mod
from aml_ai.str.domain.reference_search import masked_query
from aml_ai.str.infrastructure import reference_embedding as re_mod
from aml_ai.str.infrastructure.reference_search_repository import ReferenceSearchRepository
from tests.conftest import ROOT
from tests.str.retriever_search_support import FAN_IN_FAN_OUT_SEED, insert_chunk, vec
from tests.str.test_reference_search import _Embed, _hit, _Repo, _req, _svc

ACCOUNT = "123456789012"


@pytest.mark.parametrize(
    "raw",
    [
        "1234 - 5678 - 9012",
        "1234  5678  9012",
        "1234-.5678 9012",
        "1234\t5678\n9012",
        "1234 -5678. 9012",
        "12-34-56-78-90-12",
    ],
)
def test_runs_of_separators_are_one_number(raw: str) -> None:
    sent = _Embed()
    _svc(sent, _Repo()).search(_req(query=f"계좌 {raw} 로 돌아옴"), None)
    assert ACCOUNT not in re.sub(r"[-.\s]", "", sent.texts[0])  # 구분자를 다 빼고 이어도 원래 숫자열 0


def test_separator_limit_keeps_far_numbers_apart() -> None:
    assert masked_query("1234    5678") == "1234    5678"  # 4글자 넘게 떨어진 숫자는 따로(각각 8자리 미만)


def test_dependency_wait_counts_toward_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    embed, repo = _Embed(), _Repo()

    def slow_service():  # noqa: ANN202 — 작업 스레드·의존성 대기 흉내
        time.sleep(0.09)
        return _svc(embed, repo)

    monkeypatch.setenv("AI_INTERNAL_KEY", "k")
    monkeypatch.setenv("RAG_ENABLED", "true")
    monkeypatch.setenv("RAG_REFERENCE_SEARCH_ENABLED", "true")
    monkeypatch.setenv("EMBEDDING_MODEL", "test-embed")
    monkeypatch.setenv("CORPUS_DIR", str(ROOT / "corpus"))
    get_settings.cache_clear()
    monkeypatch.setitem(app.dependency_overrides, router_mod._reference_search_service, slow_service)  # noqa: SLF001
    with TestClient(app) as c:
        r = c.post(
            "/v1/references/search",
            headers={"X-Internal-Key": "k", "X-Budget-Ms": "30"},
            json={"typologies": ["CYCLE"]},
        )
    assert r.status_code == HTTPStatus.BAD_GATEWAY and r.json()["code"] == "LLM_UNAVAILABLE"
    assert embed.timeouts == [] and repo.calls == 0
    get_settings.cache_clear()


def test_assembly_past_deadline_is_502() -> None:
    times = iter([0.0, 0.0, 0.0, 0.0, 4.999, 5.010, 5.010])
    with pytest.raises(LlmUnavailable):
        _svc(_Embed(), _Repo([_hit("c", "A", 0.5)]), clock=lambda: next(times)).search(_req(), None)


def test_dns_delay_does_not_hold_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    real = socket.getaddrinfo

    def slow_dns(*a, **kw):  # noqa: ANN002, ANN003, ANN202
        time.sleep(0.3)
        return real("127.0.0.1", *a[1:], **kw)

    monkeypatch.setattr(socket, "getaddrinfo", slow_dns)
    s = Settings(
        _env_file=None, LLM_API_KEY="k", EMBEDDING_MODEL="emb", LLM_API_BASE="http://dns-slow.test:9"
    )
    started = time.monotonic()
    with pytest.raises(LlmUnavailable, match="total timeout"):
        re_mod.embed_within(s, "q", started + 0.05)
    assert time.monotonic() - started < 0.05 + 0.1  # 한도 + 여유 — DNS 300ms 를 기다리지 않음


@pytest.mark.db
def test_pool_wait_past_deadline_skips_search_sql(_db_engine: Engine) -> None:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
        for row in FAN_IN_FAN_OUT_SEED:
            insert_chunk(conn, **row)
    with sessionmaker(bind=_db_engine, future=True)() as s:
        real, seen = s.execute, []

        def spy(stmt, *a, **kw):  # noqa: ANN001, ANN002, ANN003, ANN202
            seen.append(str(stmt))
            return real(stmt, *a, **kw)

        s.execute = spy  # type: ignore[method-assign]
        times = iter([10.0])  # 연결을 얻고 나니 마감(5) 지남
        with pytest.raises(LlmUnavailable):
            ReferenceSearchRepository(s).search(
                vec(1.0), ["FAN_IN"], "test-embed", deadline=5.0, clock=lambda: next(times)
            )
        assert not any("typologies &&" in q for q in seen)  # 검색 SQL 0
        assert real(text("SELECT 1")).scalar() == 1
