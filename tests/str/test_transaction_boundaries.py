"""트랜잭션 경계 단위 (SCRUM-122) — LLM/임베딩 호출 중 세션이 연결을 안 쥔다.

규칙: "LLM 호출 바로 앞에는 반드시 `end_read`, `end_read` 와 LLM 호출 사이에는 DB 읽기 금지" (docs/str/03).

이 파일은 `-m db` 아님 — SQLite in-memory Session 으로 autobegin·commit 라운드만. 운영 풀 측정은
`test_concurrent_pool.py`(-m db).

develop 에서는 `end_read` 미구현 → import·심볼·실제 흐름 전부 fail.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import VerifyStatus
from aml_ai.str.application import draft_service as draft_mod
from aml_ai.str.application import verify_service as verify_mod
from aml_ai.str.application.draft_service import DraftService
from aml_ai.str.application.verify_service import VerifyService
from aml_ai.str.infrastructure.retriever import Retriever
from tests.str.verify_service_support import (
    FakeGenerationRepository,
    FakeJudge,
    FakeVerificationRepository,
    facts_fan_in,
    judge_pass_checks,
    narrative_ok,
    stored_draft,
    verify_request,
)


@pytest.fixture
def sqlite_session() -> Iterator[Session]:
    """SQLite in-memory — autobegin·commit 라운드만."""
    engine = create_engine("sqlite:///:memory:", future=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory() as s:
        yield s


# ───────── 1) end_read 자체 라운드 ─────────


def test_end_read_closes_autobegun_read_transaction(sqlite_session: Session) -> None:
    """SELECT → autobegin → `end_read` 가 commit → `in_transaction` False."""
    from aml_ai.shared.db import end_read

    sqlite_session.execute(text("select 1"))
    assert sqlite_session.in_transaction() is True
    end_read(sqlite_session)
    assert sqlite_session.in_transaction() is False


def test_end_read_twice_is_safe(sqlite_session: Session) -> None:
    """초안 흐름은 `end_read` 를 두 자리에서 부른다 — 두 번째는 no-op."""
    from aml_ai.shared.db import end_read

    sqlite_session.execute(text("select 1"))
    end_read(sqlite_session)
    end_read(sqlite_session)
    assert sqlite_session.in_transaction() is False


# ───────── 2) 구조 확인 (심볼·필드) — develop 에선 fail ─────────


def test_draft_service_module_imports_end_read() -> None:
    assert hasattr(draft_mod, "end_read"), "draft_service 가 end_read 를 import 안 함 (SCRUM-122 미구현)"


def test_verify_service_module_imports_end_read() -> None:
    assert hasattr(verify_mod, "end_read"), "verify_service 가 end_read 를 import 안 함 (SCRUM-122 미구현)"


def test_draft_service_has_session_field() -> None:
    fields = {f.name for f in dataclasses.fields(DraftService)}
    assert "session" in fields, "DraftService.session 필드 없음 (SCRUM-122 미구현)"


def test_verify_service_has_session_field() -> None:
    fields = {f.name for f in dataclasses.fields(VerifyService)}
    assert "session" in fields, "VerifyService.session 필드 없음 (SCRUM-122 미구현)"


# ───────── 3) verify 서비스 흐름 — PASSED·CODE_FAILED 둘 다 실제 assert ─────────


def _build_verify_service(session: Session, judge: FakeJudge, draft):
    """운영 VerifyService 를 Fake 들로 조립 — `session` 은 진짜 SQLite Session."""
    get_settings.cache_clear()
    verifications = FakeVerificationRepository()
    svc = VerifyService(
        settings=get_settings(),
        session=session,
        generations=FakeGenerationRepository(draft=draft),
        verifications=verifications,
        judge=judge,
    )
    return svc, verifications


def test_verify_passed_judge_sees_no_open_read_transaction(sqlite_session: Session) -> None:
    """verify PASSED — judge.run 호출 시 `session.in_transaction() is False`."""
    sqlite_session.execute(text("select 1"))  # load_draft 흉내 autobegin
    draft = stored_draft(facts_fan_in(), narrative_ok())
    judge = FakeJudge(checks=judge_pass_checks(), session=sqlite_session)
    svc, _ = _build_verify_service(sqlite_session, judge, draft)

    resp = svc.verify(verify_request(narrative_ok()))

    assert resp.status is VerifyStatus.PASSED
    assert judge.in_tx_at_call == [False], "judge 호출 시 읽기 트랜잭션 열려 있음 — end_read 미호출"


def test_verify_code_failed_still_commits_before_save(sqlite_session: Session) -> None:
    """CODE_FAILED 경로 — judge 는 안 부름. `end_read` 후 `verifications.save` autobegin + commit."""
    sqlite_session.execute(text("select 1"))  # load_draft autobegin
    narrative = narrative_ok()
    narrative[0] = narrative[0].model_copy(update={"evidence_ids": [999]})  # OUT_OF_SCOPE
    draft = stored_draft(facts_fan_in(), narrative_ok())
    judge = FakeJudge(checks=judge_pass_checks(), session=sqlite_session)
    svc, verifs = _build_verify_service(sqlite_session, judge, draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.CODE_FAILED
    assert judge.calls == 0, "CODE_FAILED 라면 judge 호출 안 함"
    assert len(verifs.saved) == 1, "end_read 뒤 save 가 autobegin 으로 저장 성공해야"


# ───────── 4) Retriever enabled=True — 임베딩 호출 시 세션이 열려 있지 않다 ─────────


class _TrackingEmbedder:
    """embed() 호출 시 session.in_transaction() 기록."""

    def __init__(self, session: Session) -> None:
        self._s = session
        self.in_tx_at_call: list[bool] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.in_tx_at_call.append(self._s.in_transaction())
        return [[0.0] * 8 for _ in texts]


def test_retriever_embed_called_after_end_read(
    sqlite_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """서비스가 _references 호출 전 `end_read` → 임베딩 중 `session.in_transaction() is False`.

    draft_service._generate 가 하는 것처럼 end_read → retrieve 호출. _search 는 monkeypatch 로 비움.
    """
    from aml_ai.shared.db import end_read

    sqlite_session.execute(text("select 1"))  # 읽기 autobegin 흉내
    end_read(sqlite_session)  # 서비스가 _references 전에 반납(실제 _generate 동작)
    embedder = _TrackingEmbedder(sqlite_session)
    retriever = Retriever(sqlite_session, embedder, enabled=True)
    monkeypatch.setattr(Retriever, "_search", lambda self, vec, typ: [])
    retriever.retrieve(facts_fan_in())  # 실측 facts 재사용
    assert embedder.in_tx_at_call == [False]


# ───────── 5) draft 서비스 흐름 — DraftService._generate 를 Fake 들로 조립해 돌림 ─────────


def test_draft_service_generator_sees_no_open_read_transaction(sqlite_session: Session) -> None:
    """DraftService 를 가짜 reader·fewshot·retriever(enabled)·generator·generations 로 조립해 `_generate` 를 돌림.

    `_FakeGenerator.generate()` 호출 시점·`_FakeRetriever.retrieve()` 안 embed 시점 모두
    `session.in_transaction() is False` 여야 — end_read 가 둘 앞에서 트랜잭션을 닫은 결과.
    """
    from tests.str.draft_transaction_support import run_generate_with_fakes

    gen, retriever = run_generate_with_fakes(sqlite_session)
    assert gen.in_tx_at_call == [False], "generator.generate 호출 시 트랜잭션 열려 있음"
    assert retriever.embed_in_tx == [False], "retriever.retrieve 호출 시 트랜잭션 열려 있음"
