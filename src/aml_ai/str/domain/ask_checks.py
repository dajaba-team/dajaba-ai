"""질문 답변 코드 검사·근거 (docs/str/06 "질문 답변에 도는 코드 검사", SCRUM-290). 순수 함수.

요약 4종(`run_summary_code_checks`)을 그대로 부른 뒤 상대·자행·타행 COUNT 줄을 방향·근거 키로 다시 판정하고
(`ask_direction`, 06 10번) 묶음 범위 `EVIDENCE_IN_SCOPE` 1줄을 붙인다.
금액은 질문 답변에서만 facts 정확 값으로 좁힌다(06 8번, `ask_amounts`) — 공용 `amount_match` 는 그대로.
인용 키·근거 거래는 질문 답변 인용 키(`ask_fact_keys`, 06 9번) 기준.
초안용 `evidence_in_scope` 의 "cites 전부 빔 → MISSING" 은 안 씀 — 답의 빈 cites 는 스키마 단계에서 502.
"""

from __future__ import annotations

from collections.abc import Sequence

from aml_ai.shared.schemas.str import CheckReason, CodeCheck, CodeCheckName, Facts
from aml_ai.str.domain.ask_amounts import exact_amounts
from aml_ai.str.domain.ask_bundles import ask_fact_keys
from aml_ai.str.domain.ask_direction import has_claims, recheck, used_keys
from aml_ai.str.domain.ask_question import other_case_numbers
from aml_ai.str.domain.constants_ask import EVIDENCE_OUT_OF_SCOPE_MARK, OTHER_CASE_MARK
from aml_ai.str.domain.verification import run_summary_code_checks


def run(
    facts: Facts,
    answer: str,
    cites: Sequence[str],
    piece_keys: Sequence[str],
    question: str = "",
    case_no: str = "",
) -> list[CodeCheck]:
    """AMOUNT → DATE → COUNT → ACCOUNT_ID → EVIDENCE_IN_SCOPE. 결과 section 은 전부 None."""
    checks = run_summary_code_checks(facts, [answer], cited_evidence_ids(facts, cites, answer, question))
    checks = exact_amounts(facts, answer, cites, checks)
    checks = recheck(facts, answer, cites, checks, question)  # 06 10번 — 상대·자행·타행은 범위·근거 키로 다시
    checks.append(
        evidence_check(facts, cites, piece_keys, other_case_numbers(answer, case_no) if case_no else [])
    )
    return checks


def evidence_check(
    facts: Facts, cites: Sequence[str], piece_keys: Sequence[str], other_cases: Sequence[str] = ()
) -> CodeCheck:
    """인용 키 ⊆ ask_fact_keys(facts) ∩ 고른 묶음의 키 + 답에 이 케이스 밖 케이스 번호 없음(추가 검토 4 H6). 통과해도 1줄.

    draft_value 는 밖 키 개수만 담은 고정 표시 — cites 원문(모델 문자열)은 저장 행 `llm_answer` 에만.
    """
    allowed = set(ask_fact_keys(facts)) & set(piece_keys)
    bad = [c for c in cites if c not in allowed]
    mark = (
        EVIDENCE_OUT_OF_SCOPE_MARK.format(n=len(bad)) if bad else OTHER_CASE_MARK.format(n=len(other_cases))
    )
    fail = bool(bad or other_cases)
    return CodeCheck(
        check=CodeCheckName.EVIDENCE_IN_SCOPE,
        section=None,
        draft_value=mark if fail else None,
        source_value=None,
        match=not fail,
        reason=CheckReason.OUT_OF_SCOPE if fail else None,
    )


def cited_evidence_ids(facts: Facts, cites: Sequence[str], answer: str = "", question: str = "") -> list[int]:
    """cites 의 fact 키 → 거래 ID 합집합(`attach_evidence` 와 같은 방식). 목록 밖·거래 없는 키는 기여 0.

    답에 상대 수·자행·타행 숫자가 있으면 상대 계열 키는 **그 숫자를 뒷받침한 키만** 근거에 넣는다 — 안 쓰인 키
    (예: 입금 2 답에 덧붙인 출금 키)는 실패 사유가 아니라 근거에서만 빠진다(06 10번, 추가 검토 2).
    """
    keys = ask_fact_keys(facts)
    if has_claims(answer):
        used = used_keys(facts, answer, cites, question)
        cites = [c for c in cites if not c.startswith(_COUNTERPARTY_KEYS) or c in used]
    return sorted({i for c in cites if c in keys for i in keys[c]})


_COUNTERPARTY_KEYS = ("counterparties.", "counterparty_banks.", "counterparties_by_direction.")
