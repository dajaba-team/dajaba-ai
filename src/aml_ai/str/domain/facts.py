"""build_facts · fact_keys · attach_evidence — 정본 docs/str/04_facts.md. 순수 함수.

SCRUM-12 에서는 schemas(Facts 새 구조)만 바꿨고, 계산 규칙 구현은 SCRUM-13 이다.
규칙 한 줄 = 테스트 하나 (tests/str/test_facts.py). 바꾸려면 md 먼저.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import DraftRequest, Facts, LlmNarrativeSection, NarrativeSection
from aml_ai.str.domain.models import Subject, Transaction


def build_facts(req: DraftRequest, txs: list[Transaction], subject: Subject) -> Facts:
    """경보 + 거래 행 + 대상 → facts. inbound/outbound/internal/indirect, 통화별, paths 확인."""
    raise NotImplementedError("SCRUM-13 — docs/str/04 계산 규칙 표")


def fact_keys(facts: Facts) -> dict[str, list[int]]:
    """인용 가능한 fact 키 → 그 키의 근거 거래 ID. null fact·UNVERIFIED paths 는 키 없음."""
    raise NotImplementedError("SCRUM-13 — docs/str/04 fact 키 표")


def attach_evidence(narrative: list[LlmNarrativeSection], facts: Facts) -> list[NarrativeSection]:
    """섹션마다 cites 의 fact 키 → 거래 ID 합집합 = evidence_ids."""
    raise NotImplementedError("SCRUM-13 — docs/str/04 fact 키 표")
