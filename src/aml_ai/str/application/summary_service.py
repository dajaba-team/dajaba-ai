"""POST /v1/cases/summary (W4 말). 같은 loader → facts → masking, 프롬프트만 summary_v1, 검증은 코드 4종만."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.schemas.str import SummaryRequest, SummaryResponse


@dataclass
class SummaryService:
    settings: Settings

    @classmethod
    def build(cls, session: Session, settings: Settings) -> SummaryService:
        return cls(settings=settings)

    def summarize(self, req: SummaryRequest) -> SummaryResponse:
        raise NotImplementedError("W4 말 — docs/str/03 '/v1/cases/summary'")
