"""질문 답변 LLM 출력 — 계획(ask_plan_v1)·답(ask_answer_v1·v2 `AskAnswerOut`, v3 `AskAnswerOutV3`). 정본 docs/str/05.

규약 JSON(`ask.py`)이 아니라 LLM Structured Output 모양. 어긋나면 서비스가 `LLM_INVALID_OUTPUT`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from aml_ai.shared.schemas.common import StrictModel
from aml_ai.shared.schemas.str.ask import ASK_ANSWER_MAX, ASK_BUNDLES_MAX, OutOfScopeReason
from aml_ai.shared.text import utf16_len_nfc


class AskBundle(StrEnum):
    """묶음 8개 — 순서·이름은 docs/str/04 "질문 답변 묶음" 표."""

    SUBJECT = "subject"
    FLOWS = "flows"
    COUNTERPARTIES = "counterparties"
    FORMATS = "formats"
    PATHS = "paths"
    OBSERVATIONS = "observations"
    SCORE_REASONS = "score_reasons"
    RULE_FACTS = "rule_facts"


class AskPlanKind(StrEnum):
    FACT = "FACT"
    WHY = "WHY"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class AskPlanOut(StrictModel):
    kind: AskPlanKind
    out_of_scope_reason: OutOfScopeReason | None
    bundles: list[AskBundle] = Field(max_length=ASK_BUNDLES_MAX)

    @model_validator(mode="after")
    def _pair(self) -> AskPlanOut:
        if self.kind is AskPlanKind.OUT_OF_SCOPE:
            if self.out_of_scope_reason is None or self.bundles:
                raise ValueError("OUT_OF_SCOPE needs a reason and bundles=[]")
        elif self.out_of_scope_reason is not None or not self.bundles:
            raise ValueError("FACT/WHY need reason=null and 1..3 bundles")
        if len(self.bundles) != len(set(self.bundles)):
            raise ValueError("bundles must not contain duplicates")
        return self


class AskAnswerOut(StrictModel):
    answerable: bool
    answer: Annotated[str, StringConstraints(strip_whitespace=False)] | None
    cites: list[str]

    @field_validator("cites")
    @classmethod
    def _cites_nonblank_unique(cls, v: list[str]) -> list[str]:
        if any(not c.strip() for c in v) or len(v) != len(set(v)):
            raise ValueError("cites must be non-blank and unique")
        return v

    @model_validator(mode="after")
    def _answerable_needs_answer_and_cites(self) -> AskAnswerOut:
        if not self.answerable:
            return self  # 서비스가 answer·cites 를 무시하고 NO_DATA
        if self.answer is None or not self.answer.strip():
            raise ValueError("answerable=true needs a non-blank answer")
        if utf16_len_nfc(self.answer) > ASK_ANSWER_MAX:
            raise ValueError(f"answer must be ≤{ASK_ANSWER_MAX} UTF-16 code units after NFC")
        if not self.cites:
            raise ValueError("answerable=true needs at least one cite")
        return self


class AskAnswerOutV3(StrictModel):
    """ask_answer_v3·v4(SCRUM-362) — cites 없음(코드가 자리표 키에서 만듦, docs/str/04 "답 자리표")."""

    answerable: bool
    answer: Annotated[str, StringConstraints(strip_whitespace=False)] | None

    @model_validator(mode="after")
    def _answerable_needs_answer(self) -> AskAnswerOutV3:
        if not self.answerable:
            return self  # 서비스가 answer 를 무시하고 NO_DATA
        if self.answer is None or not self.answer.strip():
            raise ValueError("answerable=true needs a non-blank answer")
        if utf16_len_nfc(self.answer) > ASK_ANSWER_MAX:
            raise ValueError(f"answer must be ≤{ASK_ANSWER_MAX} UTF-16 code units after NFC")
        return self
