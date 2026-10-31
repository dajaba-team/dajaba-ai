"""초안: 검증 → 선점 → 생성 → 근거 연결 → 펜싱 저장 (docs/str/03)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import AiError, FencedOut, InvalidRequest, RetrievalUnavailable
from aml_ai.shared.infrastructure.embedding_client import make_embedding_client
from aml_ai.shared.infrastructure.llm_client import make_llm_client
from aml_ai.shared.schemas.str import DraftRequest, DraftResponse, Facts, Reference
from aml_ai.shared.time_utils import utc_now
from aml_ai.shared.versioning import generation_meta
from aml_ai.str.domain import fact_keys as fact_keys_domain
from aml_ai.str.domain import facts as facts_domain
from aml_ai.str.domain import masking
from aml_ai.str.domain.request_hash import request_hash
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.generation_repository import ClaimReuse, GenerationRepository
from aml_ai.str.infrastructure.narrative_generator import NarrativeGenerator
from aml_ai.str.infrastructure.retriever import Retriever
from aml_ai.str.infrastructure.transaction_reader import TransactionReader

log = logging.getLogger(__name__)


@dataclass
class DraftService:
    settings: Settings
    reader: TransactionReader
    fewshot: FewshotStore
    retriever: Retriever
    generator: NarrativeGenerator
    generations: GenerationRepository
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def build(
        cls, session: Session, settings: Settings, *, clock: Callable[[], float] = time.monotonic
    ) -> DraftService:
        llm = make_llm_client(settings)
        return cls(
            settings=settings,
            reader=TransactionReader(session),
            fewshot=FewshotStore(session),
            retriever=Retriever(session, make_embedding_client(settings), enabled=settings.rag_enabled),
            generator=NarrativeGenerator(llm, settings, clock=clock),
            generations=GenerationRepository(session, settings),
            clock=clock,
        )

    def create(self, req: DraftRequest) -> DraftResponse:
        problem = facts_domain.request_problem(req)
        if problem:
            raise InvalidRequest(problem)
        deadline = self.clock() + self.settings.draft_budget_s
        claim = self.generations.claim(req, request_hash(req))
        if isinstance(claim, ClaimReuse):
            return claim.response
        try:
            response = self._generate(req, claim.generation_id, deadline)
            self.generations.finish(
                claim.generation_id,
                facts=response.facts,
                response_payload=response.model_dump(mode="json"),
                meta=response.generation_meta.model_dump(mode="json"),
            )
            return response
        except Exception as exc:
            code = exc.code if isinstance(exc, AiError) else "INTERNAL"
            message = exc.message if isinstance(exc, AiError) else "internal error"
            self._fail(claim.generation_id, code, message)
            raise

    def _fail(self, generation_id: str, code: str, message: str) -> None:
        try:
            self.generations.fail(generation_id, code=code, message=message)
        except FencedOut:
            log.warning("generation_fenced_out", extra={"generation_id": generation_id})
            raise

    def _generate(self, req: DraftRequest, generation_id: str, deadline: float) -> DraftResponse:
        txs = self.reader.load_transactions(req.evidence_transaction_ids)
        if not facts_domain.has_reportable(txs):
            raise InvalidRequest("no reportable transactions")
        subject = self.reader.load_subject(req.alert, txs)
        # 3·4 — 순수
        facts = facts_domain.build_facts(req, txs, subject)
        facts_masked = masking.mask_for_llm(facts)
        # 5
        examples = self.fewshot.pick_examples(facts.typology)
        references = self._references(facts)
        gen = self.generator.generate(
            facts_masked,
            list(fact_keys_domain.fact_keys(facts).keys()),
            examples,
            references,
            req.investigator_notes,
            deadline=deadline,
        )
        # 8 — 순수: cites 의 fact 키 → evidence_ids
        narrative = fact_keys_domain.attach_evidence(gen.narrative, facts)
        meta = generation_meta(
            self.settings,
            llm_model=gen.llm_model,
            prompt_version=gen.prompt_version,
            few_shot_ids=[e.example_id for e in examples],
            references=[r.model_dump(exclude={"text"}) for r in references],
            tokens_in=gen.tokens_in,
            tokens_out=gen.tokens_out,
            latency_ms=gen.latency_ms,
        )
        return DraftResponse(
            produced_at=utc_now(),
            draft_id=req.draft_id,
            generation_id=generation_id,
            facts=facts,
            narrative=narrative,
            generation_meta=meta,
            verification=None,
        )

    def _references(self, facts: Facts) -> list[Reference]:
        try:
            return self.retriever.retrieve(facts)
        except RetrievalUnavailable:
            log.warning("retrieval_unavailable")
            return []
