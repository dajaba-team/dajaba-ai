"""run_code_checks — 정본 docs/str/06 코드 검증 표. 순수 함수, 정규식 + Decimal.

원칙: 거짓 양성 감수, 허용 오차 0. 코드가 잡은 건 LLM 이 뭐라 해도 fail.
TODO(W3): 네 함수 구현. 오류 주입 1~6 (tests/str/test_injection.py -m deterministic) 이 곧 테스트.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CodeCheck, CodeCheckName, Facts, NarrativeSection, Section


def run_code_checks(
    facts: Facts, narrative: list[NarrativeSection], transaction_ids: list[int]
) -> list[CodeCheck]:
    checks: list[CodeCheck] = []
    checks += amount_match(facts, narrative)
    checks += date_match(facts, narrative)
    checks += counterparty_count(facts, narrative)
    checks += evidence_in_scope(narrative, transaction_ids)
    return checks


def amount_match(facts: Facts, narrative: list[NarrativeSection]) -> list[CodeCheck]:
    """본문의 금액(쉼표·만/억 정규화) ⊆ {total_amount} ∪ 허용 소수. 통화 단어 ±10자 문맥만 금액으로 본다."""
    raise NotImplementedError("W3 — docs/str/06 AMOUNT_MATCH")


def date_match(facts: Facts, narrative: list[NarrativeSection]) -> list[CodeCheck]:
    """모든 날짜가 [period_start.date, period_end.date] 안. WHAT_WHEN_WHERE 에 날짜가 없으면 fail."""
    raise NotImplementedError("W3 — docs/str/06 DATE_MATCH")


def counterparty_count(facts: Facts, narrative: list[NarrativeSection]) -> list[CodeCheck]:
    """'N개 계좌/상대/거래처' 가 있으면 전부 counterparty_count 와 같아야 함."""
    raise NotImplementedError("W3 — docs/str/06 COUNTERPARTY_COUNT")


def evidence_in_scope(narrative: list[NarrativeSection], transaction_ids: list[int]) -> list[CodeCheck]:
    """evidence_ids 전부 transaction_ids 안. 6개 섹션 전부 빈 배열이면 fail."""
    allowed = set(transaction_ids)
    out: list[CodeCheck] = []
    for s in narrative:
        bad = [i for i in s.evidence_ids if i not in allowed]
        out.append(
            CodeCheck(
                check=CodeCheckName.EVIDENCE_IN_SCOPE,
                section=s.section,
                draft_value=",".join(map(str, bad)) or None,
                source_value=None,
                match=not bad,
            )
        )
    if all(not s.evidence_ids for s in narrative):
        out.append(
            CodeCheck(
                check=CodeCheckName.EVIDENCE_IN_SCOPE,
                section=None,
                draft_value="no evidence in any section",
                source_value=None,
                match=False,
            )
        )
    return out


__all__ = [
    "run_code_checks",
    "amount_match",
    "date_match",
    "counterparty_count",
    "evidence_in_scope",
    "Section",
]
