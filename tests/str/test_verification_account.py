"""ACCOUNT_ID_MATCH 단위 (SCRUM-58). 정본 docs/str/06.

facts_fan_in.json: subject.account_key = 010_8000EBD30 (끝 4자 BD30, bank_id 010).
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CheckReason, CodeCheckName, Facts, SectionV1, SectionV2
from tests.conftest import FIXTURES, load_json
from tests.str.verification_support import account, facts_fan_in

# ---------- 정상 (match) ----------


@pytest.mark.parametrize("section", [SectionV1.SUMMARY, SectionV2.METHOD])
@pytest.mark.parametrize(
    "text",
    [
        "대상 계좌(010_****BD30) 입금",  # 마스킹 형태 + bank_id
        "계좌 ****BD30 입금",  # 마스킹 꼬리
        "끝자리 BD30 입금",
        "원본 010_8000EBD30 입금",
    ],
)
def test_match(section: SectionV1 | SectionV2, text: str) -> None:
    checks = account(facts_fan_in(), section, text)
    assert checks and all(c.match for c in checks), text


def test_match_other_bank_sample() -> None:
    """facts_cases.json 주체 010_S0000001 → 끝 4자 0001."""
    data = load_json(FIXTURES / "facts_fan_in.json")
    data["subject"]["account_key"] = "010_S0000001"
    facts = Facts.model_validate(data)
    checks = account(facts, SectionV1.SUMMARY, "끝자리 0001 입금")
    assert checks and all(c.match for c in checks)


def test_overlapping_single_row() -> None:
    """`010_****BD30` 은 ①번·②번 패턴 둘 다 걸리지만 긴 쪽 우선 — 결과 1줄 (★A 4)."""
    checks = account(facts_fan_in(), SectionV1.SUMMARY, "대상 계좌(010_****BD30) 입금")
    assert len(checks) == 1 and checks[0].match


# ---------- 오탐 막기 (결과 없음) ----------


@pytest.mark.parametrize(
    "text",
    [
        "R04_CYCLE 룰로 탐지",  # 룰 ID (앞이 영문 R)
        "R05_STACK 패턴",
        "2022-09-02 입금 발생",  # 날짜
        "합계 42,750.50 US Dollar 입금",  # 금액 자리
    ],
)
def test_no_result_for_non_account(text: str) -> None:
    assert account(facts_fan_in(), SectionV1.SUMMARY, text) == []


# ---------- 잡기 (MISMATCH) ----------


def test_mismatch_counterparty() -> None:  # 오류 주입 #18
    checks = account(facts_fan_in(), SectionV1.SUMMARY, "상대 계좌 ****A1F2 로 송금")
    assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks)


def test_mismatch_bank_id() -> None:
    """끝 4자리 같아도 은행 번호가 다르면 MISMATCH (★A 4)."""
    checks = account(facts_fan_in(), SectionV1.SUMMARY, "011_****BD30 입금")
    assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks)


def test_mismatch_tail_masked() -> None:
    """`*` 가 뒤쪽에 있어 끝 4자리를 못 읽는 모양은 MISMATCH (★A 4)."""
    checks = account(facts_fan_in(), SectionV1.SUMMARY, "010_SX000*** 로 이동")
    assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks)


def test_check_name() -> None:
    checks = account(facts_fan_in(), SectionV1.SUMMARY, "010_****BD30 입금")
    assert all(c.check is CodeCheckName.ACCOUNT_ID_MATCH for c in checks)
