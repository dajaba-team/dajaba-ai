"""오류 주입 — SCRUM-60 활성 (4·5·6·20·24·25·26·27·28·30·31).

도우미를 `run_code_checks` 로 바꿈(모듈 docstring 약속). 해당 `check` 이름만 골라 단언.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheckName,
    Facts,
    RevisedNarrativeSection,
    SectionV1,
    SectionV2,
)
from aml_ai.str.domain import verification
from tests.str.verification_support import facts_cycle, facts_fan_in, narrative_ok


def _run(facts: Facts, section, text: str) -> list:
    """`run_code_checks` 호출 — 섹션 하나·cites·evidence_ids 는 범위 안으로."""
    v1_scope = list(facts.inbound.transaction_ids) or [1, 2, 3]
    n = [RevisedNarrativeSection(section=section, text=text, cites=[], evidence_ids=[])]
    return verification.run_code_checks(facts, n, v1_scope)


def _only(checks, name: CodeCheckName) -> list:
    return [c for c in checks if c.check is name]


def test_injection_04_counterparty_count_mismatch() -> None:
    """상대 수 `13개 계좌`(실제 cp=3) → COUNT_MATCH MISMATCH."""
    checks = _run(facts_fan_in(), SectionV1.SUMMARY, "13개 계좌")
    bad = [c for c in _only(checks, CodeCheckName.COUNT_MATCH) if not c.match]
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_injection_05_cites_out_of_scope() -> None:
    """cites 에 FACT_KEYS 밖 키 → EVIDENCE_IN_SCOPE OUT_OF_SCOPE."""
    n = [RevisedNarrativeSection.model_validate(s.model_dump()) for s in narrative_ok()]
    n[0] = n[0].model_copy(update={"cites": [*n[0].cites, "no_such_fact_key"]})
    checks = verification.run_code_checks(facts_fan_in(), n, [1, 2, 3])
    bad = [c for c in _only(checks, CodeCheckName.EVIDENCE_IN_SCOPE) if not c.match]
    assert bad and any(c.reason is CheckReason.OUT_OF_SCOPE for c in bad)


def test_injection_06_all_cites_empty_missing() -> None:
    """모든 섹션 cites·evidence_ids 빔 → EVIDENCE_IN_SCOPE MISSING 1줄."""
    n = [
        RevisedNarrativeSection(section=s.section, text=s.text, cites=[], evidence_ids=[])
        for s in narrative_ok()
    ]
    checks = verification.run_code_checks(facts_fan_in(), n, [1, 2, 3])
    assert any(
        c.check is CodeCheckName.EVIDENCE_IN_SCOPE and c.section is None and c.reason is CheckReason.MISSING
        for c in checks
    )


def test_injection_20_korean_numeral_count_unparsed() -> None:
    """한글 수사 + 단위 `서른한 개 계좌` → COUNT_MATCH UNPARSED."""
    checks = _run(facts_fan_in(), SectionV1.SUMMARY, "서른한 개 계좌")
    bad = [c for c in _only(checks, CodeCheckName.COUNT_MATCH) if not c.match]
    assert bad and all(c.reason is CheckReason.UNPARSED for c in bad)


def test_injection_24_cycle_verified_pass() -> None:
    """VERIFIED 고리에 `3개 계좌를 거쳐 … 순환 경로 2개` — 통과해야 함."""
    checks = _run(facts_cycle("VERIFIED"), SectionV1.HOW, "3개 계좌를 거쳐 순환 경로 2개")
    bad = [c for c in _only(checks, CodeCheckName.COUNT_MATCH) if not c.match]
    assert not bad


def test_injection_25_cycle_verified_wrong_mismatch() -> None:
    """같은 VERIFIED facts 에 `4개 계좌를 거쳐`·`순환 경로 3개` → MISMATCH."""
    checks = _run(facts_cycle("VERIFIED"), SectionV1.HOW, "4개 계좌를 거쳐 순환 경로 3개")
    bad = [c for c in _only(checks, CodeCheckName.COUNT_MATCH) if not c.match]
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_injection_26_cycle_unverified_mismatch() -> None:
    """UNVERIFIED 인데 경로 숫자 인용 → MISMATCH (미결 26 AI 몫)."""
    checks = _run(facts_cycle("UNVERIFIED"), SectionV1.HOW, "순환 경로 2개")
    bad = [c for c in _only(checks, CodeCheckName.COUNT_MATCH) if not c.match]
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_injection_27_payment_format_count_mismatch() -> None:
    """`ACH 50건`(facts ACH=3) → COUNT_MATCH MISMATCH."""
    checks = _run(facts_fan_in(), SectionV1.HOW, "ACH 50건")
    bad = [c for c in _only(checks, CodeCheckName.COUNT_MATCH) if not c.match]
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_injection_28_same_bank_mismatch() -> None:
    """`자행 5 계좌`(facts 자행=0) → COUNT_MATCH MISMATCH."""
    checks = _run(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "자행 5 계좌")
    bad = [c for c in _only(checks, CodeCheckName.COUNT_MATCH) if not c.match]
    assert bad and all(c.reason is CheckReason.MISMATCH for c in bad)


def test_injection_30_opinion_blank_missing() -> None:
    """v2 OPINION 섹션이 `자료 없음` 만 → OPINION_PRESENT MISSING."""
    opinion = RevisedNarrativeSection(section=SectionV2.OPINION, text="자료 없음", cites=[], evidence_ids=[])
    checks = verification.run_code_checks(facts_fan_in(), [opinion], [1, 2, 3])
    bad = [c for c in checks if c.check is CodeCheckName.OPINION_PRESENT and not c.match]
    assert bad and all(c.reason is CheckReason.MISSING for c in bad)


def test_injection_31_opinion_present_pass() -> None:
    """v2 OPINION 에 정상 문장 → OPINION_PRESENT match."""
    opinion = RevisedNarrativeSection(
        section=SectionV2.OPINION,
        text="집중 입금(FAN_IN) 유형에 해당하여 자금세탁 의심 여부에 대한 검토가 필요함.",
        cites=["typology"],
        evidence_ids=[],
    )
    checks = verification.run_code_checks(facts_fan_in(), [opinion], [1, 2, 3])
    opin = [c for c in checks if c.check is CodeCheckName.OPINION_PRESENT]
    assert opin and all(c.match for c in opin)
