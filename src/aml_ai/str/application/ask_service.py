"""`/v1/cases/ask` — 질문 답변 서비스 (SCRUM-290, 정본 docs/str/03·04·05). 선점·펜싱 없음.

290-1: facts → 연결 반납 → 질문 가리기 → 계획 LLM → 범위 밖이면 응답·저장. 범위 안은 묶음 조각까지 만든 뒤
`INTERNAL` FAILED — 답·코드 검사·근거는 290-2 에서 이 자리를 채운다(03).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.db import end_read
from aml_ai.shared.errors import AiError, InvalidRequest
from aml_ai.shared.infrastructure.llm_client import make_llm_client
from aml_ai.shared.schemas.str import (
    AskGenerationMeta,
    AskRequest,
    AskResponse,
    AskStatus,
    Facts,
)
from aml_ai.shared.schemas.str.ask_llm import AskPlanKind
from aml_ai.shared.text import utf16_len_nfc
from aml_ai.shared.time_utils import utc_now
from aml_ai.str.domain import facts as facts_domain
from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.domain.ask_question import mask_question
from aml_ai.str.domain.constants_ask import ASK_PLAN_PROMPT
from aml_ai.str.domain.display_labels_check import Labels
from aml_ai.str.infrastructure.ask_llm import AskLlm, PlanResult
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.summary_repository import SummaryRepository
from aml_ai.str.infrastructure.transaction_reader import TransactionReader

log = logging.getLogger(__name__)
KIND_ASK = "ASK"
ANSWER_NOT_WIRED = "answer step not wired"  # 290-2 에서 지움


@dataclass
class AskService:
    settings: Settings
    session: Session  # SCRUM-122 — end_read(self.session)
    reader: TransactionReader
    llm: AskLlm
    repo: SummaryRepository
    labels: Labels
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def build(
        cls, session: Session, settings: Settings, *, clock: Callable[[], float] = time.monotonic
    ) -> AskService:
        return cls(
            settings=settings,
            session=session,
            reader=TransactionReader(session),
            llm=AskLlm(make_llm_client(settings), settings, clock=clock),
            repo=SummaryRepository(session),
            labels=load_display_labels(),
            clock=clock,
        )

    def ask(self, req: AskRequest) -> AskResponse:
        self._validate(req)
        deadline = self.clock() + self.settings.ask_budget_s
        generation_id = f"g-{uuid.uuid4().hex[:8]}"
        try:
            facts = self._load_facts(req)
            end_read(self.session)  # SCRUM-122 — LLM 호출 전 연결 반납
            question = mask_question(req.question)  # 04 — LLM 에 가는 질문만, 저장은 원문
            plan = self.llm.plan(question, deadline=deadline)
            if plan.out.kind is AskPlanKind.OUT_OF_SCOPE:
                response = self._out_of_scope(req, generation_id, plan)
            else:
                response = self._answer(req, facts, plan)
            self._save_success(req, generation_id, facts, response, plan)
        except Exception as exc:
            code = exc.code if isinstance(exc, AiError) else "INTERNAL"
            message = exc.message if isinstance(exc, AiError) else "internal error"
            self._save_failure(req, generation_id, code, message)
            raise
        self._log_done(req, response)
        return response

    def _validate(self, req: AskRequest) -> None:
        """evidence_transaction_ids ⊆ alert.transaction_ids — 요약과 같은 규칙(shared/01)."""
        if not set(req.evidence_transaction_ids) <= set(req.alert.transaction_ids):
            raise InvalidRequest("evidence must be subset of alert.transaction_ids")

    def _load_facts(self, req: AskRequest) -> Facts:
        inp = req.to_facts_input()
        txs = self.reader.load_transactions(inp.evidence_transaction_ids)
        if not facts_domain.has_reportable(txs):
            raise InvalidRequest("no reportable transactions")
        subject = self.reader.load_subject(inp.alert, txs)
        return facts_domain.build_facts(inp, txs, subject)

    def _answer(self, req: AskRequest, facts: Facts, plan: PlanResult) -> AskResponse:
        """290-1 — 묶음 조각까지 만들고 멈춤. 290-2 에서 답 LLM·코드 검사·근거로 바뀐다(03)."""
        extract(facts, req.alert.rule_id, [b.value for b in plan.out.bundles], self.labels)
        raise AiError(ANSWER_NOT_WIRED)

    def _out_of_scope(self, req: AskRequest, generation_id: str, plan: PlanResult) -> AskResponse:
        """LLM 1회로 끝 — 답 프롬프트 null·묶음 [] ·토큰·지연은 계획 호출분(shared/01)."""
        meta = AskGenerationMeta(
            llm_model=plan.llm_model,
            prompt_version=None,
            plan_prompt_version=ASK_PLAN_PROMPT,
            bundles=[],
            server_version=self.settings.server_version,
            tokens_in=plan.tokens_in,
            tokens_out=plan.tokens_out,
            latency_ms=plan.latency_ms,
        )
        return AskResponse(
            produced_at=utc_now(),
            case_no=req.case_no,
            generation_id=generation_id,
            status=AskStatus.OUT_OF_SCOPE,
            kind=None,
            out_of_scope_reason=plan.out.out_of_scope_reason,
            answer=None,
            cites=[],
            evidence_ids=[],
            code_checks=[],
            generation_meta=meta,
        )

    def _save_success(
        self, req: AskRequest, generation_id: str, facts: Facts, response: AskResponse, plan: PlanResult
    ) -> None:
        payload = response.model_dump(mode="json")
        payload["plan"] = plan.out.model_dump(mode="json")
        self.repo.save(
            generation_id=generation_id,
            case_no=req.case_no,
            request=req.model_dump(mode="json"),
            facts=facts,
            response_payload=payload,
            meta=response.generation_meta.model_dump(mode="json"),
            status="SUCCEEDED",
            kind=KIND_ASK,
        )

    def _save_failure(self, req: AskRequest, generation_id: str, code: str, message: str) -> None:
        try:
            self.repo.save(
                generation_id=generation_id,
                case_no=req.case_no,
                request=req.model_dump(mode="json"),
                facts=None,
                response_payload={},
                meta={},
                status="FAILED",
                error=f"{code}: {message[:48]}".strip(),
                kind=KIND_ASK,
            )
        except Exception:
            log.warning("ask_save_failure_failed", extra={"generation_id": generation_id})

    @staticmethod
    def _log_done(req: AskRequest, response: AskResponse) -> None:
        """NFR-COM-04 — 케이스 번호·상태·길이·시간만. 질문·답 본문은 찍지 않는다."""
        log.info(
            "ask_done",
            extra={
                "case_no": req.case_no,
                "generation_id": response.generation_id,
                "status": response.status.value,
                "question_len": utf16_len_nfc(req.question),
                "latency_ms": response.generation_meta.latency_ms,
            },
        )
