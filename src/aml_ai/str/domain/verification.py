"""run_code_checks — 정본 docs/str/06 코드 검증 표(유형별 대조 6종). 순수 함수, 정규식 + Decimal.

원칙: 거짓 양성 감수, 허용 오차 0. 코드가 잡은 건 LLM 이 뭐라 해도 fail. 못 읽은 표현은 UNPARSED.
SCRUM-58 로 `amount_match`·`account_id_match`, SCRUM-59 로 `date_match`, SCRUM-60 로 `count_match`·
`evidence_in_scope` cites 기준 — 각각 전용 모듈. `opinion_present` 는 여기.
오류 주입 (tests/str/test_injection.py -m deterministic) 이 곧 테스트.
"""

from __future__ import annotations

import unicodedata

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheck,
    CodeCheckName,
    Facts,
    NarrativeSection,
    NarrativeSectionBase,
    Section,
    SectionV1,
    SectionV2,
)
from aml_ai.str.domain.fact_keys import FactKeys, fact_keys
from aml_ai.str.domain.verification_account import account_id_match
from aml_ai.str.domain.verification_amount import amount_match
from aml_ai.str.domain.verification_count import count_match
from aml_ai.str.domain.verification_date import date_match

# OPINION 공란으로 간주할 표현 (SCRUM-47 안건 6-5) — strip·NFC 뒤 비교.
OPINION_BLANK_STRINGS: frozenset[str] = frozenset({"자료 없음", "해당 없음", "없음", "-"})


def run_code_checks(
    facts: Facts, narrative: list[NarrativeSectionBase], transaction_ids: list[int]
) -> list[CodeCheck]:
    keys = fact_keys(facts)
    checks: list[CodeCheck] = []
    checks += amount_match(facts, narrative)
    checks += date_match(facts, narrative)
    checks += count_match(facts, narrative)
    checks += account_id_match(facts, narrative)
    checks += evidence_in_scope(narrative, transaction_ids, keys)
    checks += opinion_present(narrative)  # v2 전용 — 함수 안에서 집합 확인
    return checks


def evidence_in_scope(
    narrative: list[NarrativeSectionBase],
    transaction_ids: list[int],
    fact_keys_result: FactKeys,
) -> list[CodeCheck]:
    """cites ⊆ fact_keys(facts) + evidence_ids ⊆ evidence_scope (SCRUM-60 ★A 5).

    섹션 cites 에 fact_keys 밖 키가 있거나 evidence_ids 가 scope 밖이면 OUT_OF_SCOPE.
    모든 섹션 cites 가 전부 비면 MISSING 1줄 (근거 없는 초안·수정본).
    """
    allowed_ids = set(transaction_ids)
    allowed_keys = set(fact_keys_result.keys())
    out: list[CodeCheck] = []
    for s in narrative:
        bad_keys = [k for k in s.cites if k not in allowed_keys]
        bad_ids = [i for i in s.evidence_ids if i not in allowed_ids]
        bad = bad_keys + [str(i) for i in bad_ids]
        out.append(
            CodeCheck(
                check=CodeCheckName.EVIDENCE_IN_SCOPE,
                section=s.section,
                draft_value=",".join(bad) or None,
                source_value=None,
                match=not bad,
                reason=CheckReason.OUT_OF_SCOPE if bad else None,
            )
        )
    if all(not s.cites for s in narrative):
        out.append(
            CodeCheck(
                check=CodeCheckName.EVIDENCE_IN_SCOPE,
                section=None,
                draft_value="no cites in any section",
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


def run_summary_code_checks(
    facts: Facts, summary_lines: list[str], transaction_ids: list[int]
) -> list[CodeCheck]:
    """요약 응답 `summary_lines[≤6]` 을 한 덩어리 본문으로 4종만 검사 (SCRUM-129 ★A 2).

    AMOUNT·DATE·COUNT·ACCOUNT_ID — `EVIDENCE_IN_SCOPE`·`OPINION_PRESENT` 는 안 돎(요약에 `cites` 없음,
    facts 는 `evidence_transaction_ids` 로만 계산되므로 숫자 범위 밖 거래 생성 불가).

    내부적으로 임의 섹션 enum(`SectionV1.SUMMARY`) 을 쓴 뒤 결과 `section` 을 전부 `None` 으로 교체.
    """
    pseudo = NarrativeSection(
        section=SectionV1.SUMMARY,
        text="\n".join(summary_lines),
        cites=[],
        evidence_ids=transaction_ids,
    )
    checks: list[CodeCheck] = []
    checks += amount_match(facts, [pseudo])
    checks += date_match(facts, [pseudo])
    checks += count_match(facts, [pseudo])
    checks += account_id_match(facts, [pseudo])
    return [c.model_copy(update={"section": None}) for c in checks]


__all__ = [
    "run_code_checks",
    "run_summary_code_checks",
    "amount_match",
    "date_match",
    "count_match",
    "account_id_match",
    "evidence_in_scope",
    "opinion_present",
    "Section",
]
