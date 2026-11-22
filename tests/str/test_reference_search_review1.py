"""SCRUM-309 추가 검토 1 회귀 — 검색용 가리기 · 임베딩 호출 전체 마감 · 429 분류 · 유사도 하한 · DB 마감 · manifest 기동 검사."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from aml_ai import main as app_main
from aml_ai.shared.config import Settings
from aml_ai.shared.errors import BudgetExceeded, DbUnavailable, LlmUnavailable
from aml_ai.shared.versioning import reference_search_problem
from aml_ai.str.domain.reference_search import arrange, masked_query
from aml_ai.str.infrastructure import reference_embedding as re_mod
from aml_ai.str.infrastructure.reference_search_repository import ReferenceSearchRepository
from tests.conftest import ROOT
from tests.str.retriever_search_support import FAN_IN_FAN_OUT_SEED, insert_chunk, vec
from tests.str.test_reference_search import _Embed, _hit, _in, _Repo, _req, _svc

KEYED = {"LLM_API_KEY": "k", "EMBEDDING_MODEL": "emb", "EMBEDDING_DIM": 2}


@pytest.mark.parametrize(
    "raw",
    [
        "110-123-456789",
        "110 123 456789",
        "110.123.456789",
        "123456789012",
        "10_8000EBD30",
        "8000EBD30AB",
        "3333-01-1234567",
    ],
)
def test_search_mask_hides_whole_number(raw: str) -> None:
    sent = _Embed()
    _svc(sent, _Repo()).search(_req(query=f"계좌 {raw} 로 돌아옴"), None)
    digits = re.sub(r"\D", "", raw)
    got = re.sub(r"[-.\s]", "", sent.texts[0])
    assert raw not in sent.texts[0] and (
        len(digits) < 8 or digits not in got
    )  # 구분자 빼고 이어도 원래 숫자열 없음


def test_search_mask_keeps_comma_amounts_and_short_numbers() -> None:
    out = masked_query("15,000,000원 3회 송금 2022-09-07")
    assert (
        out is not None and "15,000,000원" in out and "3회" in out and "****0907" in out
    )  # 날짜(8자리)는 가림


def test_ask_mask_unchanged() -> None:
    from aml_ai.str.domain.ask_question import mask_question

    assert mask_question("110-123-456789") == "110-123-456789"  # 질문 답변 쪽은 그대로(알고 남김, str/04)


def _transport(handler) -> httpx.MockTransport:  # noqa: ANN001
    return httpx.MockTransport(handler)


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"model": "emb", "data": [{"embedding": [0.1, 0.2], "index": 0}]})


def test_embed_within_ok() -> None:
    s = Settings(_env_file=None, **KEYED)
    assert re_mod.embed_within(s, "q", _in(1.0), transport=_transport(_ok)) == [0.1, 0.2]


def test_embed_within_total_deadline_cancels() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.5)  # 헤더·본문이 늦게 옴
        return _ok(request)

    with pytest.raises(LlmUnavailable, match="total timeout"):
        re_mod.embed_within(Settings(_env_file=None, **KEYED), "q", _in(0.05), transport=_transport(slow))


@pytest.mark.parametrize(
    ("body", "expected"),
    [({"error": {"code": "insufficient_quota"}}, BudgetExceeded), ({"error": "insufficient_quota"}, LlmUnavailable),
     ({"error": {}}, LlmUnavailable), ("not json", LlmUnavailable), (["x"], LlmUnavailable),
     ({"error": {"code": "rate_limit_exceeded"}}, LlmUnavailable)],
)  # fmt: skip
def test_429_classification(body: object, expected: type) -> None:
    content = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    t = _transport(lambda r: httpx.Response(429, content=content))
    with pytest.raises(expected):
        re_mod.embed_within(Settings(_env_file=None, **KEYED), "q", _in(1.0), transport=t)


@pytest.mark.parametrize(
    "bad",
    [
        {"model": "other", "data": [{"embedding": [0.1, 0.2]}]},
        {"model": "emb", "data": [{"embedding": [0.1]}]},
    ],
)
def test_embed_within_checks_model_and_dim(bad: dict) -> None:
    with pytest.raises(LlmUnavailable):
        re_mod.embed_within(
            Settings(_env_file=None, **KEYED),
            "q",
            _in(1.0),
            transport=_transport(lambda r: httpx.Response(200, json=bad)),
        )


def test_similarity_floor() -> None:
    assert arrange([_hit("n", "A", -0.2)], top_k=5, per_doc=3) == []
    assert [h.chunk_id for h in arrange([_hit("z", "A", 0.0), _hit("n", "B", -0.1)], top_k=5, per_doc=3)] == [
        "z"
    ]
    out = _svc(_Embed(), _Repo([_hit("n", "A", -0.2)])).search(_req(), None)
    assert out.status.value == "EMPTY"


def test_cache_hit_still_checks_budget_before_db() -> None:
    embed, repo = _Embed(), _Repo()
    svc = _svc(embed, repo, clock=lambda: 0.0)
    svc.search(_req(), None)  # 캐시에 넣음
    clock = iter([0.0, 6.0]).__next__
    svc.clock = clock
    with pytest.raises(LlmUnavailable):
        svc.search(_req(), None)  # 캐시 적중 — DB 전에 예산 0 이하
    assert repo.calls == 1 and len(embed.texts) == 1


def test_slow_db_is_not_200() -> None:
    times = iter([0.0, 0.0, 0.0, 0.0, 6.0, 6.0])
    with pytest.raises(LlmUnavailable):
        _svc(_Embed(), _Repo([_hit("c", "A", 0.5)]), clock=lambda: next(times)).search(_req(), None)


def test_repo_gets_absolute_deadline() -> None:
    repo = _Repo()
    _svc(_Embed(), repo, clock=lambda: 0.0).search(_req(), 1200)
    assert repo.deadline == pytest.approx(1.2)


@pytest.mark.db
def test_statement_timeout_is_503(_db_engine: Engine) -> None:
    with _db_engine.begin() as conn:
        conn.execute(text("TRUNCATE ai.reference_chunks"))
        for row in FAN_IN_FAN_OUT_SEED:
            insert_chunk(conn, **row)
    with sessionmaker(bind=_db_engine, future=True)() as s:
        real = s.execute

        def slow(stmt, *a, **kw):  # noqa: ANN001, ANN002, ANN003, ANN202
            if "typologies &&" in str(stmt):
                real(text("SELECT pg_sleep(0.3)"))
            return real(stmt, *a, **kw)

        s.execute = slow  # type: ignore[method-assign]
        with pytest.raises(DbUnavailable):
            ReferenceSearchRepository(s).search(
                vec(1.0), ["FAN_IN"], "test-embed", deadline=0.05, clock=lambda: 0.0
            )
        assert real(text("SELECT 1")).scalar() == 1


def test_startup_needs_manifest_when_enabled(tmp_path: Path) -> None:
    on = {"RAG_ENABLED": True, "RAG_REFERENCE_SEARCH_ENABLED": True, "EMBEDDING_MODEL": "emb"}
    assert reference_search_problem(Settings(_env_file=None, **on, CORPUS_DIR=str(tmp_path))) is not None
    assert reference_search_problem(Settings(_env_file=None, **{**on, "EMBEDDING_MODEL": " "})) is not None
    assert (
        reference_search_problem(Settings(_env_file=None, CORPUS_DIR=str(tmp_path))) is None
    )  # 끔이면 안 봄
    assert (
        reference_search_problem(Settings(_env_file=None, **on, CORPUS_DIR=str(ROOT / "corpus"))) is None
    )  # 리포 manifest


def test_lifespan_fails_without_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    s = Settings(
        _env_file=None,
        RAG_ENABLED=True,
        RAG_REFERENCE_SEARCH_ENABLED=True,
        EMBEDDING_MODEL="emb",
        CORPUS_DIR=str(tmp_path),
    )
    monkeypatch.setattr(app_main, "get_settings", lambda: s)

    async def enter() -> None:
        async with app_main.lifespan(app_main.app):
            pass

    with pytest.raises(RuntimeError, match="manifest"):
        asyncio.run(enter())
