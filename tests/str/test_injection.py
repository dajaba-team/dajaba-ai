"""오류 주입 (docs/str/08 표).

SCRUM-58 로 1·2·15·17·18·29 결정적 활성. 나머지 결정적(3·4·5·6·13·16·19~22·24~28·30~34)은 skip.
LLM 층(7~12·14·23)은 -m live. **검사 함수를 직접 부름** — `run_code_checks` 는 59·60 전까지 터짐.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheckName,
    Facts,
    NarrativeSection,
    SectionV1,
)
from aml_ai.str.domain import verification
from tests.conftest import FIXTURES, load_json

ACTIVE = [1, 2, 15, 17, 18, 29]
SKIPPED_DET = [3, 4, 5, 6, 13, 16, 19, 20, 21, 22, 24, 25, 26, 27, 28, 30, 31, 32, 33, 34]
CASES_LIVE = [7, 8, 9, 10, 11, 12, 14, 23]


def _base_facts() -> Facts:
    return Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))


def _facts_total(total: str) -> Facts:
    data = load_json(FIXTURES / "facts_fan_in.json")
    data["inbound"]["by_currency"][0]["total"] = total
    return Facts.model_validate(data)


def _facts_with_range(min_: str, max_: str) -> Facts:
    data = load_json(FIXTURES / "facts_fan_in.json")
    data["amount_range"] = [{"currency": "USD", "min": min_, "max": max_}]
    return Facts.model_validate(data)


def _section(text: str) -> NarrativeSection:
    return NarrativeSection(section=SectionV1.SUMMARY, text=text, cites=[], evidence_ids=[])


def _check(fn: Callable, facts: Facts, text: str) -> list:
    return fn(facts, [_section(text)])


# ---------- 활성 (SCRUM-58) ----------


def test_injection_01_amount_value_mismatch() -> None:
    """금액 320,000,000 → 32,000,000 US Dollar."""
    checks = _check(verification.amount_match, _facts_total("320000000.00"), "입금 32,000,000 US Dollar")
    assert checks and all(not c.match for c in checks)
    assert all(c.reason is CheckReason.MISMATCH and c.check is CodeCheckName.AMOUNT_MATCH for c in checks)


def test_injection_02_korean_unit_pass() -> None:
    """금액을 한글 단위 `3억 2천만 US Dollar` — 통과해야 함 (거짓 양성 검사)."""
    checks = _check(verification.amount_match, _facts_total("320000000.00"), "입금 3억 2천만 US Dollar")
    assert checks and all(c.match for c in checks)


def test_injection_15_currency_mismatch() -> None:
    """값은 맞고 통화만 틀림 `320,000,000 EUR`."""
    checks = _check(verification.amount_match, _facts_total("320000000.00"), "입금 320,000,000 EUR")
    assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks)


@pytest.mark.parametrize("text", ["입금 약 3억 US Dollar", "입금 삼억 이천만 US Dollar"])
def test_injection_17_unparsed(text: str) -> None:
    """근사·한글 수사 → UNPARSED (조용히 통과 안 함)."""
    checks = _check(verification.amount_match, _base_facts(), text)
    assert checks and all(not c.match and c.reason is CheckReason.UNPARSED for c in checks)


def test_injection_18_counterparty_account() -> None:
    """상대 계좌 식별자 `****A1F2` → MISMATCH."""
    checks = _check(verification.account_id_match, _base_facts(), "상대 계좌 ****A1F2 로 송금")
    assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks)
    assert all(c.check is CodeCheckName.ACCOUNT_ID_MATCH for c in checks)


def test_injection_29_amount_range_match() -> None:
    """amount_range min·max 사이 건당 `2,000,000 US Dollar` — 통과해야 함 (거짓 양성 검사)."""
    checks = _check(
        verification.amount_match,
        _facts_with_range("1500000.00", "22000000.00"),
        "건당 2,000,000 US Dollar 송금",
    )
    assert checks and all(c.match for c in checks)


# ---------- 아직 skip (SCRUM-59·60·61 뒤 활성) ----------


@pytest.mark.deterministic
@pytest.mark.parametrize("case", SKIPPED_DET)
def test_injection_deterministic_pending(case: int) -> None:
    pytest.skip(f"SCRUM-59·60·61 — 오류 주입 #{case} (docs/str/08)")


@pytest.mark.live
@pytest.mark.parametrize("case", CASES_LIVE)
def test_injection_live(case: int) -> None:
    pytest.skip(f"W4 수동 — 오류 주입 #{case}")
