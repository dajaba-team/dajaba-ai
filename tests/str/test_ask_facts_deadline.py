"""SCRUM-413 질문 답변 facts 조회 시간 제한 — 가짜 시계·가짜 세션 (docs/str/03 질문 답변 2). DB·LLM 0.

남은 시간이 있으면 조회 전에 같은 세션에 남은 ms · 0 이하면 조회 0·502 · 57014·55P03 → 502 · 다른 DB 오류 그대로.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from aml_ai.shared.errors import LlmUnavailable
from aml_ai.str.infrastructure.transaction_reader import TransactionReader
from tests.shared.db_deadline_support import SET_CONFIG, Events, FakeClock, FakeSession, db_error
from tests.str.ask_service_support import StubLlm, ask_request, build_service, plan_text
from tests.str.summary_service_support import StubReader

T0 = 1000.0


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


@dataclass
class SpyReader(StubReader):
    """순서 기록 — bound_to_deadline 이 raise 하거나, 조회가 DB 오류를 낼 수 있음."""

    order: list[str] = field(default_factory=list)
    bound_args: list[tuple] = field(default_factory=list)
    bound_error: Exception | None = None
    tx_error: Exception | None = None
    subject_error: Exception | None = None

    def bound_to_deadline(self, deadline, clock) -> None:  # type: ignore[no-untyped-def]
        self.order.append("bound")
        self.bound_args.append((deadline, clock))
        if self.bound_error is not None:
            raise self.bound_error

    def load_transactions(self, ids):  # type: ignore[no-untyped-def]
        self.order.append("load_transactions")
        if self.tx_error is not None:
            raise self.tx_error
        return super().load_transactions(ids)

    def load_subject(self, alert, txs):  # type: ignore[no-untyped-def]
        self.order.append("load_subject")
        if self.subject_error is not None:
            raise self.subject_error
        return super().load_subject(alert, txs)


def _service(reader: SpyReader | StubReader, llm: StubLlm | None = None):  # type: ignore[no-untyped-def]
    svc, repo = build_service(llm or StubLlm([plan_text()]), clock=lambda: T0)
    svc.reader = reader
    return svc, repo


def test_bound_runs_before_reads_with_request_deadline() -> None:
    reader = SpyReader()
    svc, _ = _service(reader)
    svc.ask(ask_request())
    assert reader.order == ["bound", "load_transactions", "load_subject"]
    ((deadline, clock),) = reader.bound_args
    assert deadline == T0 + svc.settings.ask_budget_s and clock is svc.clock


def test_normal_path_response_and_saved_row_unchanged() -> None:
    """정상 경로 diff 0 — 시간 제한을 거는 읽기와 거는 것 없는 읽기의 응답·저장 내용이 같다."""
    base_svc, base_repo = _service(StubReader())
    spy_svc, spy_repo = _service(SpyReader())
    a, b = base_svc.ask(ask_request()), spy_svc.ask(ask_request())
    drop = {"generation_id"}
    assert a.model_dump(exclude=drop) == b.model_dump(exclude=drop)
    (ra,), (rb,) = base_repo.saved, spy_repo.saved
    assert _strip(ra) == _strip(rb)
    assert _strip(ra["response_payload"]) == _strip(rb["response_payload"])


def _strip(row: dict) -> dict:
    """생성 ID 는 매번 새로 — 그 밖 저장 칸·응답 본문은 같아야 함(before_commit 은 함수라 뺌)."""
    return {
        k: _strip(v) if k == "response_payload" else v
        for k, v in row.items()
        if k not in {"generation_id", "before_commit"}
    }


def test_expired_before_reads_is_502_without_reads_or_llm() -> None:
    reader = SpyReader(bound_error=LlmUnavailable("ask facts deadline"))
    llm = StubLlm([plan_text()])
    svc, repo = _service(reader, llm)
    with pytest.raises(LlmUnavailable):
        svc.ask(ask_request())
    assert reader.order == ["bound"] and llm.calls == []
    (row,) = repo.saved
    assert row["status"] == "FAILED" and row["error"].startswith("LLM_UNAVAILABLE: ")


@pytest.mark.parametrize("sqlstate", ["57014", "55P03"])
@pytest.mark.parametrize("where", ["tx", "subject"])
def test_timeout_during_reads_is_llm_unavailable(sqlstate: str, where: str) -> None:
    kw = {"tx_error": db_error(sqlstate)} if where == "tx" else {"subject_error": db_error(sqlstate)}
    llm = StubLlm([plan_text()])
    svc, repo = _service(SpyReader(**kw), llm)
    with pytest.raises(LlmUnavailable):
        svc.ask(ask_request())
    assert llm.calls == []
    (row,) = repo.saved
    assert row["status"] == "FAILED" and row["error"].startswith("LLM_UNAVAILABLE: ")


def test_other_db_error_is_not_mapped() -> None:
    """시간 초과가 아닌 DB 오류(연결 끊김 등)는 지금처럼 그대로 올라감 → 500 INTERNAL."""
    err = db_error("08006")
    svc, repo = _service(SpyReader(tx_error=err))
    with pytest.raises(type(err)) as caught:
        svc.ask(ask_request())
    assert caught.value is err
    (row,) = repo.saved
    assert row["status"] == "FAILED" and row["error"].startswith("INTERNAL: ")


# ── TransactionReader.bound_to_deadline — 같은 세션에 shared.db 도우미 ──


def test_reader_bound_sets_remaining_ms_on_its_session() -> None:
    ev = Events()
    TransactionReader(FakeSession(ev)).bound_to_deadline(T0 + 0.3, FakeClock(ev, T0))
    (sql,) = ev.sqls()
    assert SET_CONFIG in sql and list(ev.params()[0].values()) == ["300ms"]
    assert ev.index("connection") < ev.index("clock")


def test_reader_bound_expired_raises_llm_unavailable_without_sql() -> None:
    ev = Events()
    with pytest.raises(LlmUnavailable):
        TransactionReader(FakeSession(ev)).bound_to_deadline(T0, FakeClock(ev, T0 + 0.01))
    assert ev.sqls() == []


def test_reader_bound_expired_after_set_raises_llm_unavailable() -> None:
    ev = Events()
    with pytest.raises(LlmUnavailable):
        TransactionReader(FakeSession(ev)).bound_to_deadline(
            T0 + 0.3, FakeClock(ev, T0, jump_at=2, jump_to=T0 + 1)
        )
    assert len(ev.sqls()) == 1


# ── API 모양 — 시간 초과 응답이 지금 LLM deadline 초과 응답과 같은 모양 ──


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from aml_ai.main import app
    from aml_ai.shared.config import get_settings

    monkeypatch.setenv("AI_INTERNAL_KEY", "test-ask-key")
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c, app
    get_settings.cache_clear()


def _post(client, app, svc, monkeypatch):  # type: ignore[no-untyped-def]
    from aml_ai.str.api import router as router_mod
    from tests.conftest import EXAMPLES, load_json

    monkeypatch.setitem(app.dependency_overrides, router_mod._ask_service, lambda: svc)
    return client.post(
        "/v1/cases/ask",
        headers={"X-Internal-Key": "test-ask-key"},
        json=load_json(EXAMPLES / "ask_request.json"),
    )


def test_api_facts_timeout_matches_llm_deadline_response(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    c, app = client
    timed_out, _ = _service(SpyReader(tx_error=db_error("57014")))
    late_llm, _ = _service(StubReader())
    late_llm.llm.plan = lambda *_a, **_k: (_ for _ in ()).throw(LlmUnavailable("ask deadline passed"))  # type: ignore[method-assign]
    a = _post(c, app, timed_out, monkeypatch)
    b = _post(c, app, late_llm, monkeypatch)
    assert a.status_code == b.status_code == HTTPStatus.BAD_GATEWAY
    assert a.json()["code"] == b.json()["code"] == "LLM_UNAVAILABLE"
    assert set(a.json()) == set(b.json())
