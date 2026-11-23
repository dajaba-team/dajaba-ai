"""`/v1/cases/ask` — 질문 답변 서비스 (SCRUM-290, 정본 docs/str/03·04·05). 선점·펜싱 없음.

facts → 연결 반납 → 질문 가리기 → 계획 LLM → 범위 밖이면 응답·저장. 범위 안은 묶음 조각 → 답 LLM →
코드 검사·근거 → 응답·저장(03). 응답 조립은 `ask_answer`, 검사는 `domain.ask_checks`.
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
from aml_ai.shared.errors import AiError, InvalidRequest, LlmUnavailable
from aml_ai.shared.infrastructure.llm_client import make_llm_client
from aml_ai.shared.schemas.str import AskRequest, AskResponse, Facts
from aml_ai.shared.schemas.str.ask_llm import AskPlanKind
from aml_ai.shared.text import utf16_len_nfc
from aml_ai.str.application.ask_answer import follow_up_plan, in_scope_response, out_of_scope_response
from aml_ai.str.domain import facts as facts_domain
from aml_ai.str.domain.ask_bundles import extract, with_flows
from aml_ai.str.domain.ask_question import blocked_before_plan, mask_question
from aml_ai.str.domain.ask_scope import AskScope, ask_scope
from aml_ai.str.domain.display_labels_check import Labels
from aml_ai.str.domain.facts_direction import with_direction
from aml_ai.str.infrastructure.ask_llm import AnswerResult, AskLlm, PlanResult
from aml_ai.str.infrastructure.display_labels import load_display_labels
from aml_ai.str.infrastructure.summary_repository import SummaryRepository
from aml_ai.str.infrastructure.transaction_reader import TransactionReader

log = logging.getLogger(__name__)
KIND_ASK = "ASK"


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
        labels = load_display_labels()
        return cls(
            settings=settings,
            session=session,
            reader=TransactionReader(session),
            llm=AskLlm(make_llm_client(settings), settings, clock=clock, labels=labels),
            repo=SummaryRepository(session),
            labels=labels,
            clock=clock,
        )

    def ask(self, req: AskRequest) -> AskResponse:
        self._validate(req)
        deadline = self.clock() + self.settings.ask_budget_s
        generation_id = f"g-{uuid.uuid4().hex[:8]}"
        try:
            facts, scope = self._load_facts(req)
            end_read(self.session)  # SCRUM-122 — LLM 호출 전 연결 반납
            question = mask_question(req.question)  # 04 — LLM 에 가는 질문만, 저장은 원문
            follow_up = blocked_before_plan(
                req.question, req.case_no
            )  # 04 이어지는 질문·다른 케이스 — 호출 0
            plan = follow_up_plan() if follow_up else self.llm.plan(question, deadline=deadline)
            ans: AnswerResult | None = None
            if plan.out.kind is AskPlanKind.OUT_OF_SCOPE:
                response = out_of_scope_response(req, generation_id, plan, self.settings.server_version)
            else:
                response, ans = self._answer(req, generation_id, facts, plan, question, deadline, scope)
            self._save_success(req, generation_id, facts, response, plan, ans, deadline, by_code=follow_up)
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

    def _load_facts(self, req: AskRequest) -> tuple[Facts, AskScope]:
        inp = req.to_facts_input()
        txs = self.reader.load_transactions(inp.evidence_transaction_ids)
        if not facts_domain.has_reportable(txs):
            raise InvalidRequest("no reportable transactions")
        subject = self.reader.load_subject(inp.alert, txs)
        accounts = {req.alert.account_key} | {k for t in txs for k in (t.from_account_key, t.to_account_key)}
        scope = ask_scope(
            req.evidence_transaction_ids, req.alert.transaction_ids, accounts, subject.account_entities
        )
        facts = with_direction(facts_domain.build_facts(inp, txs, subject), txs)  # 04 — 질문 답변만 방향 칸
        return facts, scope  # 범위 — 배타·부재 이름표용(추가 검토 3 H3)

    def _answer(
        self,
        req: AskRequest,
        generation_id: str,
        facts: Facts,
        plan: PlanResult,
        question: str,
        deadline: float,
        scope: AskScope | None = None,
    ) -> tuple[AskResponse, AnswerResult]:
        """묶음 조각 → 답 LLM(1회) → 코드 검사·근거 (03 8·9)."""
        bundles = with_flows([b.value for b in plan.out.bundles], question)  # 04 "계획 보강" — meta ≤3
        piece = extract(facts, req.alert.rule_id, bundles, self.labels, scope=scope)
        ans = self.llm.answer(question, piece, deadline=deadline)
        sv = self.settings.server_version
        return in_scope_response(req, generation_id, facts, plan, piece, ans, sv, self.labels), ans

    def _save_success(
        self,
        req: AskRequest,
        generation_id: str,
        facts: Facts,
        response: AskResponse,
        plan: PlanResult,
        ans: AnswerResult | None,
        deadline: float,
        *,
        by_code: bool = False,
    ) -> None:
        """response = API 응답 + plan + llm_answer(답 호출 때만 — 자리표 그대로인 원문, UNVERIFIED 본문은 여기에만, 06).

        남은 시간 안에서만 성공 저장(03 10단계): 남은 ≤ 0 이면 안 함, 문장·잠금 대기를 남은 시간으로, 커밋 직전 재확인.
        """
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise LlmUnavailable("ask deadline passed before save")
        payload = response.model_dump(mode="json")
        payload["plan"] = plan.out.model_dump(mode="json")
        if by_code:
            payload["plan"]["source"] = "code"  # 계획 LLM 안 돎(저장 행만, 응답 모양 그대로)
        if ans is not None:
            payload["llm_answer"] = ans.out.model_dump(mode="json")
        self.repo.save(
            generation_id=generation_id,
            case_no=req.case_no,
            request=req.model_dump(mode="json"),
            facts=facts,
            response_payload=payload,
            meta=response.generation_meta.model_dump(mode="json"),
            status="SUCCEEDED",
            kind=KIND_ASK,
            timeout_s=remaining,
            before_commit=lambda: self._check_deadline(deadline),
        )

    def _check_deadline(self, deadline: float) -> None:
        if self.clock() > deadline:
            raise LlmUnavailable("ask deadline passed before commit")

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
