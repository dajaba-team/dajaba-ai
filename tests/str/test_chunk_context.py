"""SCRUM-308-3 청크 맥락 — 머리말 · 스위치(v4 만) · 프로세스 상태 · `retrieval_version` 꼬리 · 검색 표 · 기동 검사 (DB 0)."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from aml_ai import main as app_main
from aml_ai.shared import chunk_context_state, versioning
from aml_ai.shared.config import Settings
from aml_ai.str.application import draft_service
from aml_ai.str.domain.chunk_context import context_header, context_text
from aml_ai.str.domain.constants_rag_query import REFERENCE_CTX_TABLE, REFERENCE_TABLE
from aml_ai.str.infrastructure import chunk_context_check as check
from aml_ai.str.infrastructure.retriever_sql import candidates_sql, cosines_sql
from tests.str.test_rag_rerank import LogSpy

ON = {"RAG_CHUNK_CONTEXT_ENABLED": True, "NARRATIVE_PROMPT": "narrative_v4", "RAG_ENABLED": True}


@pytest.fixture(autouse=True)
def _reset_state():
    chunk_context_state.set_verified(False)
    yield
    chunk_context_state.set_verified(False)


def test_header_format_and_missing_year() -> None:
    assert context_header("Funnel Accounts", "FinCEN", 2014, 3) == "Funnel Accounts — FinCEN, 2014, p.3"
    assert context_header("Red Flags", "FFIEC", None, 5) == "Red Flags — FFIEC, p.5"  # 연도 칸만 생략
    assert context_text("H", "본문") == "H\n본문"


@pytest.mark.parametrize(("title", "publisher"), [("", "P"), ("T", None), (" ", "P")])
def test_header_needs_title_and_publisher(title: str, publisher: str | None) -> None:
    with pytest.raises(ValueError):
        context_header(title, publisher, 2020, 1)


@pytest.mark.parametrize(
    ("env", "active"),
    [
        (ON, True),
        ({**ON, "NARRATIVE_PROMPT": "narrative_v3"}, False),
        ({**ON, "RAG_CHUNK_CONTEXT_ENABLED": False}, False),
    ],
)
def test_active_only_on_v4(env: dict, active: bool) -> None:
    s = Settings(_env_file=None, **env)
    assert s.rag_chunk_context_active is active
    chunk_context_state.set_verified(True)
    assert chunk_context_state.in_use(s) is active  # 검증돼도 끔·v3 면 안 씀


def test_in_use_needs_startup_verification() -> None:
    assert chunk_context_state.in_use(Settings(_env_file=None, **ON)) is False


def test_retrieval_version_tail_only_when_in_use() -> None:
    s = Settings(_env_file=None, **ON, EMBEDDING_MODEL="emb", RAG_RERANK_ENABLED=True)
    assert "+ctx" not in (versioning.retrieval_version(s) or "")  # 확인 못 한 표 — 꼬리 없음
    chunk_context_state.set_verified(True)
    v = versioning.retrieval_version(s) or ""
    assert v.endswith("+ctx:v1+rr:rerank_v1") and v.index("+ctx:v1") < v.index("+rr:")


def test_length_check_assumes_ctx_when_enabled() -> None:
    s = Settings(_env_file=None, **ON, EMBEDDING_MODEL="e" * 111)  # 111 + 1 + 8 = 120, +ctx:v1 7 → 127
    assert versioning.retrieval_version_problem(s) is None
    s = Settings(_env_file=None, **ON, EMBEDDING_MODEL="e" * 113)  # 129
    assert versioning.retrieval_version_problem(s) is not None  # 기동 전이라도 켬이면 꼬리를 셈


def test_sql_same_shape_only_table_differs() -> None:
    for f in (True, False):
        cur, ctx = (
            str(candidates_sql(REFERENCE_TABLE, typology_filter=f)),
            str(candidates_sql(REFERENCE_CTX_TABLE, typology_filter=f)),
        )
        assert cur.replace(REFERENCE_TABLE, "T") == ctx.replace(REFERENCE_CTX_TABLE, "T")
        assert "embedding_model = :model" in cur and "ORDER BY d + 0, chunk_id" in cur
    assert str(cosines_sql(REFERENCE_CTX_TABLE)).count(REFERENCE_CTX_TABLE) == 1
    with pytest.raises(ValueError):
        candidates_sql("ai.other; DROP", typology_filter=True)


@pytest.mark.parametrize("verified", [True, False])
def test_draft_retriever_table(monkeypatch: pytest.MonkeyPatch, verified: bool) -> None:
    chunk_context_state.set_verified(verified)
    monkeypatch.setattr(draft_service, "make_embedding_client", lambda s: SimpleNamespace(model="emb"))
    r = draft_service._retriever(MagicMock(), Settings(_env_file=None, **ON), MagicMock())  # noqa: SLF001
    assert r._table == (REFERENCE_CTX_TABLE if verified else REFERENCE_TABLE)  # noqa: SLF001


def _opener(problem: str | None = None, *, fail: Exception | None = None, calls: list | None = None):  # noqa: ANN202
    @contextmanager
    def open_session():  # noqa: ANN202
        (calls if calls is not None else []).append(1)
        if fail:
            raise fail
        yield MagicMock()

    return open_session, problem


def test_startup_off_does_not_touch_db() -> None:
    calls: list = []
    opener, _ = _opener(calls=calls)
    check.verify_on_startup(Settings(_env_file=None), opener)
    assert calls == [] and chunk_context_state._verified is False  # noqa: SLF001


def test_startup_db_unreachable_uses_current_table(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = LogSpy()
    monkeypatch.setattr(check, "log", spy)
    opener, _ = _opener(fail=OperationalError("x", {}, Exception("down")))
    check.verify_on_startup(Settings(_env_file=None, **ON), opener)
    assert chunk_context_state.in_use(Settings(_env_file=None, **ON)) is False
    assert [w[0] for w in spy.records] == ["chunk_context_unverified"]


def test_startup_mismatch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "ctx_table_problem", lambda s, m, d: "새 표 행 수 1 ≠ 지금 표 2")
    with pytest.raises(RuntimeError, match="RAG_CHUNK_CONTEXT_ENABLED"):
        check.verify_on_startup(Settings(_env_file=None, **ON), _opener()[0])
    assert chunk_context_state._verified is False  # noqa: SLF001


def test_startup_match_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "ctx_table_problem", lambda s, m, d: None)
    check.verify_on_startup(Settings(_env_file=None, **ON), _opener()[0])
    assert chunk_context_state.in_use(Settings(_env_file=None, **ON)) is True


def test_lifespan_runs_check(monkeypatch: pytest.MonkeyPatch) -> None:
    s = Settings(_env_file=None, **ON, EMBEDDING_MODEL="emb")
    monkeypatch.setattr(app_main, "get_settings", lambda: s)
    monkeypatch.setattr(app_main, "_open_session", _opener()[0])
    monkeypatch.setattr(check, "ctx_table_problem", lambda session, m, d: "새 표 없음(마이그레이션 0007)")

    async def enter() -> None:
        async with app_main.lifespan(app_main.app):
            pass

    with pytest.raises(RuntimeError, match="새 표 없음"):
        asyncio.run(enter())
