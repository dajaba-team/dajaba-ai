"""POST /v1/cases/summary (W4 말). 정본 docs/str/03·04."""

from __future__ import annotations

from pydantic import Field

from aml_ai.shared.schemas.alerts import Alert
from aml_ai.shared.schemas.common import StrictModel, TransactionId
from aml_ai.shared.schemas.str.draft import GenerationMeta
from aml_ai.shared.schemas.str.facts import Facts
from aml_ai.shared.schemas.str.verify import CodeCheck


class SummaryRequest(StrictModel):
    case_no: str
    alert: Alert
    evidence_transaction_ids: list[TransactionId] = Field(min_length=1)


class SummaryResponse(StrictModel):
    case_no: str
    facts: Facts
    summary_lines: list[str] = Field(min_length=1, max_length=6)
    model_focus: str | None = Field(default=None, description="'모델이 주목한 점' 한 줄 — 관측과 섞지 않음")
    code_checks: list[CodeCheck]
    generation_meta: GenerationMeta
