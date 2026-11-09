"""`DraftService._generate` 를 Fake 들로 조립해 돌리는 helper (SCRUM-122).

`test_transaction_boundaries.py` 전용 — 실제 reader·fewshot·retriever·generator·generations 대신
가짜를 넣어 LLM/임베딩 호출 시점의 `session.in_transaction()` 을 기록한다. 세션은 SQLite in-memory.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import LlmNarrativeSection, SectionV2
from aml_ai.str.application.draft_service import DraftService
from aml_ai.str.domain.models import GenerationResult, Subject, Transaction
from aml_ai.str.infrastructure.generation_repository import ClaimNew
from tests.str.facts_support import CASES, make_subject, make_txs


@dataclass
class _FakeReader:
    """load_transactions / load_subject — session 에 `select 1` 로 autobegin 유도."""

    session: Session
    txs: list[Transaction]
    subject: Subject

    def load_transactions(self, ids: list[int]) -> list[Transaction]:
        self.session.execute(text("select 1"))
        return self.txs

    def load_subject(self, alert, txs) -> Subject:  # type: ignore[no-untyped-def]
        self.session.execute(text("select 1"))
        return self.subject


@dataclass
class _FakeFewshot:
    session: Session

    def pick_examples(self, typology):  # type: ignore[no-untyped-def]
        self.session.execute(text("select 1"))
        return []


@dataclass
class _FakeRetriever:
    """enabled=True — retrieve() 안에서 임베딩 시점 session 상태 기록."""

    session: Session
    embed_in_tx: list[bool] = field(default_factory=list)

    def retrieve(self, facts):  # type: ignore[no-untyped-def]
        self.embed_in_tx.append(self.session.in_transaction())
        return []


@dataclass
class _FakeGenerator:
    """NarrativeGenerator.generate() 호출 시점 session 상태 기록 + 가짜 v2 narrative 반환."""

    session: Session
    prompt_version: str = "narrative_v2"
    in_tx_at_call: list[bool] = field(default_factory=list)

    def generate(self, facts_masked, fact_keys, examples, references, notes, *, deadline) -> GenerationResult:  # type: ignore[no-untyped-def]
        self.in_tx_at_call.append(self.session.in_transaction())
        narrative = [LlmNarrativeSection(section=s, text="x", cites=[]) for s in SectionV2]
        return GenerationResult(
            narrative=narrative,
            llm_model="stub",
            prompt_version=self.prompt_version,
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
            request_payload={},
            raw_response="{}",
        )


@dataclass
class _FakeJudge:
    """SCRUM-147 — 평가자 호출 안 나게 전부 5점. 트랜잭션 경계 테스트는 이 분기까지 안 와도 됨."""

    session: Session
    in_tx_at_call: list[bool] = field(default_factory=list)

    def run(self, facts_masked, narrative, *, deadline, fact_keys=None):  # type: ignore[no-untyped-def]
        self.in_tx_at_call.append(self.session.in_transaction())
        from aml_ai.shared.schemas.str import JudgeMeta, LlmCheck
        from aml_ai.shared.schemas.str.verify import LlmCheckName
        from aml_ai.str.infrastructure.judge import JudgeResult

        checks = [LlmCheck(check=n, comment="", score=5) for n in LlmCheckName]
        meta = JudgeMeta(
            llm_model="stub", prompt_version="judge_v3", tokens_in=0, tokens_out=0, latency_ms=0, attempts=1
        )
        return JudgeResult(checks=checks, meta=meta, sections=[])


@dataclass
class _FakeRewriter:
    """SCRUM-147 — try_rewrite 가 not_triggered 로 떨어지면 호출 안 됨. 호출되면 noop GenerationResult."""

    session: Session

    def rewrite(self, **kwargs):  # type: ignore[no-untyped-def]
        narrative = [LlmNarrativeSection(section=s, text="x", cites=[]) for s in SectionV2]
        return GenerationResult(
            narrative=narrative,
            llm_model="stub",
            prompt_version="rewrite_v1",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0,
        )


@dataclass
class _FakeGenRepo:
    """claim → ClaimNew, finish/fail 는 기록만."""

    finished: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def claim(self, req, request_hash: str) -> ClaimNew:  # type: ignore[no-untyped-def]
        return ClaimNew(generation_id="g" * 32)

    def finish(self, generation_id: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
        self.finished.append(generation_id)

    def fail(self, generation_id: str, *, code: str, message: str = "") -> None:
        self.failed.append((generation_id, code))


def run_generate_with_fakes(session: Session) -> tuple[_FakeGenerator, _FakeRetriever]:
    """DraftService 를 Fake 들로 조립해 `_generate` 를 직접 호출. 생성기·retriever 반환."""
    get_settings.cache_clear()
    rows = CASES["mixed"]["transactions"]
    txs = make_txs(rows)
    subject = make_subject()
    reader = _FakeReader(session, txs, subject)
    fewshot = _FakeFewshot(session)
    retriever = _FakeRetriever(session)
    generator = _FakeGenerator(session)
    gens_repo = _FakeGenRepo()

    from tests.str.facts_support import make_req

    req = make_req(rows)
    svc = DraftService(
        settings=get_settings(),
        session=session,
        reader=reader,
        fewshot=fewshot,
        retriever=retriever,
        generator=generator,
        judge=_FakeJudge(session),
        rewriter=_FakeRewriter(session),
        generations=gens_repo,
    )
    svc._generate(req, generation_id="g" * 32, deadline=time.monotonic() + 100)
    return generator, retriever
