"""질문 답변 코드 검사·근거 (docs/str/06 "질문 답변에 도는 코드 검사", SCRUM-290). 순수 함수.

요약 4종(`run_summary_code_checks`)을 그대로 부른 뒤 묶음 범위 `EVIDENCE_IN_SCOPE` 1줄을 붙인다.
초안용 `evidence_in_scope` 의 "cites 전부 빔 → MISSING" 은 안 씀 — 답의 빈 cites 는 스키마 단계에서 502.
"""

from __future__ import annotations

from collections.abc import Sequence

from aml_ai.shared.schemas.str import CheckReason, CodeCheck, CodeCheckName, Facts
from aml_ai.str.domain.constants_ask import EVIDENCE_OUT_OF_SCOPE_MARK
from aml_ai.str.domain.fact_keys import fact_keys
from aml_ai.str.domain.verification import run_summary_code_checks


def run(facts: Facts, answer: str, cites: Sequence[str], piece_keys: Sequence[str]) -> list[CodeCheck]:
    """AMOUNT → DATE → COUNT → ACCOUNT_ID → EVIDENCE_IN_SCOPE. 결과 section 은 전부 None."""
    checks = run_summary_code_checks(facts, [answer], cited_evidence_ids(facts, cites))
    checks.append(evidence_check(facts, cites, piece_keys))
    return checks


def evidence_check(facts: Facts, cites: Sequence[str], piece_keys: Sequence[str]) -> CodeCheck:
    """인용 키 ⊆ fact_keys(facts) ∩ 고른 묶음의 키. 통과해도 1줄(match=true).

    draft_value 는 밖 키 개수만 담은 고정 표시 — cites 원문(모델 문자열)은 저장 행 `llm_answer` 에만.
    """
    allowed = set(fact_keys(facts)) & set(piece_keys)
    bad = [c for c in cites if c not in allowed]
    return CodeCheck(
        check=CodeCheckName.EVIDENCE_IN_SCOPE,
        section=None,
        draft_value=EVIDENCE_OUT_OF_SCOPE_MARK.format(n=len(bad)) if bad else None,
        source_value=None,
        match=not bad,
        reason=CheckReason.OUT_OF_SCOPE if bad else None,
    )


def cited_evidence_ids(facts: Facts, cites: Sequence[str]) -> list[int]:
    """cites 의 fact 키 → 거래 ID 합집합(`attach_evidence` 와 같은 방식). 목록 밖·거래 없는 키는 기여 0."""
    keys = fact_keys(facts)
    return sorted({i for c in cites if c in keys for i in keys[c]})
