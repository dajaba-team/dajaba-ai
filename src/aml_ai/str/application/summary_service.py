"""`/v1/cases/summary` — 케이스 요약 서비스 (SCRUM-129, 정본 docs/str/03·05·06). 선점·펜싱 없음."""

from __future__ import annotations

import logging
import re
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
    CodeCheck,
    Facts,
    GenerationMeta,
    SummaryRequest,
    SummaryResponse,
)
from aml_ai.shared.time_utils import utc_now
from aml_ai.shared.versioning import generation_meta
from aml_ai.str.domain import fact_keys as fact_keys_domain
from aml_ai.str.domain import facts as facts_domain
from aml_ai.str.domain import masking
from aml_ai.str.domain.models import SummaryGenerationResult
from aml_ai.str.domain.verification import run_summary_code_checks
from aml_ai.str.infrastructure.summary_generator import (
    SummaryGenerator,
    load_summary_fewshot,
    merge_generations,
)
from aml_ai.str.infrastructure.summary_repository import SummaryRepository
from aml_ai.str.infrastructure.transaction_reader import TransactionReader

log = logging.getLogger(__name__)
_DIGITS = re.compile(r"[0-9]")


def filter_model_focus(raw: str | None, signals: list[str]) -> tuple[str | None, bool]:
    """★A 4 — `model_signals` 이름을 글자 그대로 지운 뒤 남은 글자에 숫자가 있을 때만 `null`.

    반환: (사용할 값, 거부 여부). 신호 이름만 썼으면 지운 나머지가 공백·구두점이라 통과.
    "3건"·"24시간" 같은 관측 수치가 섞여 들어오면 거부. `raw=None` 은 그대로.
    """
    if raw is None:
        return None, False
    stripped = raw
    for name in sorted(signals, key=len, reverse=True):
        if name:
            stripped = stripped.replace(name, "")
    if _DIGITS.search(stripped):
        return None, True
    return raw, False


@dataclass
class SummaryService:
    settings: Settings
    session: Session  # SCRUM-122 — end_read(self.session)
    reader: TransactionReader
    generator: SummaryGenerator
    repo: SummaryRepository
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def build(
        cls, session: Session, settings: Settings, *, clock: Callable[[], float] = time.monotonic
    ) -> SummaryService:
        llm = make_llm_client(settings)
        return cls(
            settings=settings,
            session=session,
            reader=TransactionReader(session),
            generator=SummaryGenerator(llm, settings, clock=clock),
            repo=SummaryRepository(session),
            clock=clock,
        )

    def summarize(self, req: SummaryRequest) -> SummaryResponse:
        self._validate(req)
        inp = req.to_facts_input()
        deadline = self.clock() + self.settings.summary_budget_s
        generation_id = f"g-{uuid.uuid4().hex[:8]}"
        try:
            facts, txs = self._load_facts(inp)
            # SCRUM-122 — LLM 호출 전 연결 반납
            end_read(self.session)
            response = self._generate_and_check(req, generation_id, facts, deadline)
            self._save_success(req, generation_id, facts, response)
            return response
        except Exception as exc:
            code = exc.code if isinstance(exc, AiError) else "INTERNAL"
            message = exc.message if isinstance(exc, AiError) else "internal error"
            self._save_failure(req, generation_id, code, message)
            raise

    def _validate(self, req: SummaryRequest) -> None:
        """evidence_transaction_ids ⊆ alert.transaction_ids 확인(초안 `==` 과 달리 부분집합 허용)."""
        if not set(req.evidence_transaction_ids) <= set(req.alert.transaction_ids):
            raise InvalidRequest("evidence must be subset of alert.transaction_ids")

    def _load_facts(self, inp) -> tuple[Facts, list]:
        txs = self.reader.load_transactions(inp.evidence_transaction_ids)
        if not facts_domain.has_reportable(txs):
            raise InvalidRequest("no reportable transactions")
        subject = self.reader.load_subject(inp.alert, txs)
        return facts_domain.build_facts(inp, txs, subject), txs

    def _generate_and_check(
        self,
        req: SummaryRequest,
        generation_id: str,
        facts: Facts,
        deadline: float,
    ) -> SummaryResponse:
        facts_masked = masking.mask_for_llm(facts)
        fact_keys = list(fact_keys_domain.fact_keys(facts).keys())
        examples = load_summary_fewshot(facts.typology)
        gen = self.generator.generate(facts_masked, fact_keys, examples, deadline=deadline)
        checks = run_summary_code_checks(facts, gen.summary_lines, req.evidence_transaction_ids)
        # 코드 실패 → 남은 예산 OK 면 1회 재생성 (★A 3)
        if any(not c.match for c in checks) and self._can_regenerate(deadline):
            gen2 = self.generator.generate(facts_masked, fact_keys, examples, deadline=deadline)
            checks2 = run_summary_code_checks(facts, gen2.summary_lines, req.evidence_transaction_ids)
            gen = merge_generations(gen, gen2)
            checks = checks2
        return self._build_response(req, generation_id, facts, gen, checks)

    def _can_regenerate(self, deadline: float) -> bool:
        """SCRUM-129 리뷰 medium — 요약은 전용 임계값. 기본 15초로 첫 호출 뒤 재생성 자리 확보."""
        remaining = deadline - self.clock()
        return remaining >= self.settings.summary_regen_min_remaining_s

    def _build_response(
        self,
        req: SummaryRequest,
        generation_id: str,
        facts: Facts,
        gen: SummaryGenerationResult,
        checks: list[CodeCheck],
    ) -> SummaryResponse:
        model_focus, rejected = filter_model_focus(gen.model_focus, facts.model_signals)
        if rejected:
            log.warning("summary_model_focus_rejected", extra={"reason": "non_signal_digit"})
        meta_dict = generation_meta(
            self.settings,
            llm_model=gen.llm_model,
            prompt_version=gen.prompt_version,
            few_shot_ids=gen.few_shot_ids,
            references=[],
            tokens_in=gen.tokens_in,
            tokens_out=gen.tokens_out,
            latency_ms=gen.latency_ms,
        )
        return SummaryResponse(
            produced_at=utc_now(),
            case_no=req.case_no,
            generation_id=generation_id,
            summary_lines=gen.summary_lines,
            model_focus=model_focus,
            code_checks=checks,
            generation_meta=GenerationMeta.model_validate(meta_dict),
        )

    def _save_success(
        self, req: SummaryRequest, generation_id: str, facts: Facts, response: SummaryResponse
    ) -> None:
        self.repo.save(
            generation_id=generation_id,
            case_no=req.case_no,
            request=req.model_dump(mode="json"),
            facts=facts,
            response_payload=response.model_dump(mode="json"),
            meta=response.generation_meta.model_dump(mode="json"),
            status="SUCCEEDED",
        )

    def _save_failure(self, req: SummaryRequest, generation_id: str, code: str, message: str) -> None:
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
            )
        except Exception:
            log.warning("summary_save_failure_failed", extra={"generation_id": generation_id})
