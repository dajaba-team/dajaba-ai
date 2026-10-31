"""run_code_checks — 정본 docs/str/06 코드 검증 표(유형별 대조 5종). 순수 함수, 정규식 + Decimal.

원칙: 거짓 양성 감수, 허용 오차 0. 코드가 잡은 건 LLM 이 뭐라 해도 fail. 못 읽은 표현은 UNPARSED.
TODO(W3): AMOUNT·DATE·COUNT·ACCOUNT_ID 구현, EVIDENCE_IN_SCOPE 의 cites ⊆ fact_keys (SCRUM-13 fact_keys 뒤).
오류 주입 (tests/str/test_injection.py -m deterministic) 이 곧 테스트.
"""

from __future__ import annotations

import unicodedata

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheck,
    CodeCheckName,
    Facts,
    NarrativeSectionBase,
    Section,
    SectionV2,
)

# OPINION 공란으로 간주할 표현 (SCRUM-47 안건 6-5) — strip·NFC 뒤 비교.
OPINION_BLANK_STRINGS: frozenset[str] = frozenset({"자료 없음", "해당 없음", "없음", "-"})


def run_code_checks(
    facts: Facts, narrative: list[NarrativeSectionBase], transaction_ids: list[int]
) -> list[CodeCheck]:
    checks: list[CodeCheck] = []
    checks += amount_match(facts, narrative)
    checks += date_match(facts, narrative)
    checks += count_match(facts, narrative)
    checks += account_id_match(facts, narrative)
    checks += evidence_in_scope(narrative, transaction_ids)
    checks += opinion_present(narrative)  # v2 전용 — 함수 안에서 집합 확인
    return checks


def amount_match(facts: Facts, narrative: list[NarrativeSectionBase]) -> list[CodeCheck]:
    """금액+통화 쌍 ↔ 같은 통화의 inbound/outbound.amount. 통화 없는 숫자는 금액으로 보지 않는다."""
    raise NotImplementedError("W3 — docs/str/06 AMOUNT_MATCH")


def date_match(facts: Facts, narrative: list[NarrativeSectionBase]) -> list[CodeCheck]:
    """거래 날짜 ↔ period, 개설일 ↔ customer.onboarded_at. WHAT_WHEN_WHERE 에 거래 날짜가 없으면 MISSING."""
    raise NotImplementedError("W3 — docs/str/06 DATE_MATCH")


def count_match(facts: Facts, narrative: list[NarrativeSectionBase]) -> list[CodeCheck]:
    """건수·상대 수·경로 수 ↔ 해당 집합 (paths 는 VERIFIED 일 때만)."""
    raise NotImplementedError("W3 — docs/str/06 COUNT_MATCH")


def account_id_match(facts: Facts, narrative: list[NarrativeSectionBase]) -> list[CodeCheck]:
    """계좌 식별자 표현은 subject.account_key 끝 4자리만 통과."""
    raise NotImplementedError("W3 — docs/str/06 ACCOUNT_ID_MATCH")


def evidence_in_scope(narrative: list[NarrativeSectionBase], transaction_ids: list[int]) -> list[CodeCheck]:
    """evidence_ids ⊆ 요청 evidence_transaction_ids (밖이면 OUT_OF_SCOPE). 6개 섹션 전부 근거가 없으면 MISSING.

    TODO(W3): docs/str/06 은 cites 기준(cites ⊆ fact_keys, 전부 빈 cites → MISSING). fact_keys 가 생기면 바꾼다.
    """
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
                reason=CheckReason.OUT_OF_SCOPE if bad else None,
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
                reason=CheckReason.MISSING,
            )
        )
    return out


def opinion_present(narrative: list[NarrativeSectionBase]) -> list[CodeCheck]:
    """v2 전용 — OPINION 섹션이 공란 표현(`자료 없음·해당 없음·없음·-`)뿐이면 MISSING (SCRUM-47 안건 6-5).

    v1 집합(OPINION 섹션 없음)에서는 돌지 않는다 — 섹션 이름만 보고 분기.
    """
    opinion_sections = [s for s in narrative if s.section == SectionV2.OPINION]
    if not opinion_sections:  # v1 집합 — 검사 안 함
        return []
    out: list[CodeCheck] = []
    for s in opinion_sections:
        normalized = unicodedata.normalize("NFC", s.text).strip()
        is_blank = normalized in OPINION_BLANK_STRINGS
        out.append(
            CodeCheck(
                check=CodeCheckName.OPINION_PRESENT,
                section=s.section,
                draft_value=normalized if is_blank else None,
                source_value=None,
                match=not is_blank,
                reason=CheckReason.MISSING if is_blank else None,
            )
        )
    return out


__all__ = [
    "run_code_checks",
    "amount_match",
    "date_match",
    "count_match",
    "account_id_match",
    "evidence_in_scope",
    "opinion_present",
    "Section",
]
