"""run_summary_code_checks — 요약 줄 한 덩어리 본문에 4종 검사 (SCRUM-129 ★A 2).

- AMOUNT·DATE·COUNT·ACCOUNT_ID 4종만 — EVIDENCE_IN_SCOPE·OPINION_PRESENT 는 안 돎
- 결과 모든 `CodeCheck.section` 은 None
- 숫자가 틀린 줄은 잡힘
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CodeCheckName
from aml_ai.str.domain.verification import run_summary_code_checks
from tests.str.facts_support import CASES, build


@pytest.fixture
def facts():
    return build(CASES["mixed"])


def test_runs_only_four_kinds(facts) -> None:
    """4종만 돎 — EVIDENCE_IN_SCOPE·OPINION_PRESENT 없음."""
    checks = run_summary_code_checks(facts, ["아무 요약 줄"], transaction_ids=[1])
    names = {c.check for c in checks}
    assert CodeCheckName.EVIDENCE_IN_SCOPE not in names
    assert CodeCheckName.OPINION_PRESENT not in names
    assert names <= {
        CodeCheckName.AMOUNT_MATCH,
        CodeCheckName.DATE_MATCH,
        CodeCheckName.COUNT_MATCH,
        CodeCheckName.ACCOUNT_ID_MATCH,
    }


def test_all_sections_are_none(facts) -> None:
    """요약은 섹션 없음 — 결과 section 전부 None."""
    checks = run_summary_code_checks(facts, ["줄 하나"], transaction_ids=[1])
    assert all(c.section is None for c in checks)


def test_wrong_amount_caught(facts) -> None:
    """facts 안 금액이 아니면 AMOUNT_MATCH 실패."""
    # facts 가 가진 금액 과 다른 금액을 적음
    lines = ["보고 대상 계좌로 USD 999,999.99 입금 1건"]
    checks = run_summary_code_checks(facts, lines, transaction_ids=[1])
    amount_checks = [c for c in checks if c.check == CodeCheckName.AMOUNT_MATCH]
    assert any(c.match is False for c in amount_checks)
