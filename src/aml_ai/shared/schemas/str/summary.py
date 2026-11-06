"""규약 §6.1 — POST /v1/cases/summary 요청·응답·LLM 출력. 정본 docs/str/03·05·06·shared/01 (SCRUM-129)."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StringConstraints

from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.common import StrictModel, SystemTimestamp, TransactionId
from aml_ai.shared.schemas.scores import Reason
from aml_ai.shared.schemas.str.draft import GenerationMeta
from aml_ai.shared.schemas.str.facts_input import FactsInput
from aml_ai.shared.schemas.str.verify import CodeCheck

SUMMARY_LINE_MAX = 80  # 한 줄 ≤80자 — 05 활성
SUMMARY_LINES_MIN = 1
SUMMARY_LINES_MAX = 6

SummaryLine = Annotated[
    str,
    StringConstraints(strip_whitespace=False, min_length=1, max_length=SUMMARY_LINE_MAX),
]


class SummaryRequest(StrictModel):
    """케이스 요약 요청 — DraftRequest 와 같은 reasons·prior_alert_count·reporting_institution.

    `reasons`·`prior_alert_count` 는 **필수** — 규약 §6.1 11/6 반영(v0.4 추가 20번, SCRUM-129 ★A 1).
    `reporting_institution` 은 선택(없으면 `subject.bank_name` 폴백 — 초안과 같은 규칙).
    `evidence_transaction_ids ⊆ alert.transaction_ids` 서비스에서 검사(초안 `==` 과 달리 부분집합 허용).
    """

    case_no: str
    alert: Alert
    evidence_transaction_ids: list[TransactionId] = Field(min_length=1)
    reasons: list[Reason] = Field(description="3절 reasons 그대로. 점수가 없으면 []")
    prior_alert_count: int = Field(ge=0, description="건수만 — 내용은 보내지 않는다")
    reporting_institution: str | None = None

    def to_facts_input(self) -> FactsInput:
        """build_facts 공통 입력으로 (SCRUM-129 ★A 1)."""
        return FactsInput(
            alert=self.alert,
            evidence_transaction_ids=self.evidence_transaction_ids,
            reasons=self.reasons,
            prior_alert_count=self.prior_alert_count,
            reporting_institution=self.reporting_institution,
        )


class SummaryOut(StrictModel):
    """summary_v1 LLM 출력 스키마 — OpenAI strict json_schema (SCRUM-129)."""

    summary_lines: list[SummaryLine] = Field(min_length=SUMMARY_LINES_MIN, max_length=SUMMARY_LINES_MAX)
    model_focus: str | None  # 필수 + null 허용 — default 없음(strict 모드 규칙).


class SummaryResponse(StrictModel):
    """규약 §6.1 응답 (SCRUM-129).

    `produced_at` 은 `SystemTimestamp` — UTC `Z` 초 단위 (초안 5.2·SCRUM-52 와 같음). 백엔드
    `case_summaries.produced_at` NOT NULL 제약 때문에 필수.  `generation_id` 는 저장 행 PK 와 같음.
    `code_checks` 는 요약 줄 한 덩어리로 4종(AMOUNT·DATE·COUNT·ACCOUNT_ID) — `EVIDENCE_IN_SCOPE`·
    `OPINION_PRESENT` 안 돌림.
    """

    produced_at: SystemTimestamp
    case_no: str
    generation_id: str
    summary_lines: list[SummaryLine] = Field(min_length=SUMMARY_LINES_MIN, max_length=SUMMARY_LINES_MAX)
    model_focus: str | None = Field(description="'모델이 주목한 점' 한 줄 — 관측과 섞지 않음")
    code_checks: list[CodeCheck]
    generation_meta: GenerationMeta
