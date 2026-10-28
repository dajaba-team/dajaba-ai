"""POST /v1/str/drafts 처리 순서 (docs/str/03).

1 요청 검증(라우터) → 2 loader → 3 facts → 4 masking → 5 fewshot → 6 retrieval(실패→[])
→ 7 generate(스키마 실패 1회 재생성) → 8 [안건 17: MVP 는 verification=None] → 9 저장 → 10 응답
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.errors import RetrievalUnavailable
from aml_ai.shared.infrastructure.embedding_client import make_embedding_client
from aml_ai.shared.infrastructure.llm_client import make_llm_client
from aml_ai.shared.schemas.str import DraftRequest, DraftResponse, Reference
from aml_ai.shared.versioning import generation_meta
from aml_ai.str.domain import facts as facts_domain
from aml_ai.str.domain import masking
from aml_ai.str.infrastructure.fewshot_store import FewshotStore
from aml_ai.str.infrastructure.generation_repository import GenerationRepository
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

    @classmethod
    def build(cls, session: Session, settings: Settings) -> DraftService:
        llm = make_llm_client(settings)
        return cls(
            settings=settings,
            reader=TransactionReader(session),
            fewshot=FewshotStore(session),
            retriever=Retriever(session, make_embedding_client(settings), enabled=settings.rag_enabled),
            generator=NarrativeGenerator(llm, settings),
            generations=GenerationRepository(session),
        )

    def create(self, req: DraftRequest) -> DraftResponse:
        # 2
        txs = self.reader.load_transactions(req.evidence_transaction_ids)
        subject = self.reader.load_subject(req.alert)
        # 3·4 — 순수
        facts = facts_domain.build_facts(req, txs, subject)
        facts_masked = masking.mask_for_llm(facts)
        # 5
        examples = self.fewshot.pick_examples(facts.typology)
        # 6 — 실패해도 초안은 만든다 (docs/str/10, 오류 주입 13)
        try:
            references: list[Reference] = self.retriever.retrieve(facts)
        except RetrievalUnavailable as exc:
            log.warning("retrieval_unavailable", extra={"reason": exc.message})
            references = []
        # 7
        gen = self.generator.generate(facts_masked, examples, references, req.investigator_notes)
        # 8 — 순수: cites 의 fact 키 → evidence_ids
        narrative = facts_domain.attach_evidence(gen.narrative, facts)
        # 9
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
        # TODO(SCRUM-14): 선점(PROCESSING) → finish 펜싱. 지금은 생성 뒤 한 번에 저장
        generation_id = self.generations.save_draft(req, facts, gen, meta)
        # 10 — 원본 facts 로 응답. verification 은 안건 17 (항상 None)
        return DraftResponse(
            draft_id=req.draft_id,
            generation_id=generation_id,
            facts=facts,
            narrative=narrative,
            generation_meta=meta,
            verification=None,
        )
