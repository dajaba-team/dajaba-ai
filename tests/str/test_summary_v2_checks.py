"""SCRUM-340 Jira ② — 요약 검사(AMOUNT_MATCH)가 `62,992,819.38 유로(EUR)` 모양을 값으로 대조 — 느슨해지지 않음."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aml_ai.shared.schemas.str import CheckReason, CodeCheckName, Facts
from aml_ai.str.domain.verification import run_summary_code_checks

FIXTURES = Path(__file__).parent / "fixtures"


def _facts_eur(total: str = "62992819.38") -> Facts:
    """fan_in fixture 를 EUR 한 통화 큰 금액으로(Jira 예시 값)."""
    raw = json.loads((FIXTURES / "facts_fan_in.json").read_text(encoding="utf-8"))
    raw["inbound"]["by_currency"] = [{**raw["inbound"]["by_currency"][0], "currency": "EUR", "total": total}]
    raw["amount_range"] = [{"currency": "EUR", "min": "1000.00", "max": "3000000.00"}]
    return Facts.model_validate(raw)


def _amount(facts: Facts, line: str) -> list:
    ids = facts.inbound.transaction_ids
    return [c for c in run_summary_code_checks(facts, [line], ids) if c.check is CodeCheckName.AMOUNT_MATCH]


@pytest.mark.parametrize(
    "line",
    [
        "입금 합계는 62,992,819.38 유로(EUR)임.",  # v2 표기
        "입금 합계는 62,992,819.38 유로임.",  # 초안 v4 두 번째 등장 모양
        "입금 합계는 62,992,819.38 EUR임.",
        "입금 합계는 62992819.38 EUR임.",  # v1 모양도 그대로 match
    ],
)
def test_comma_and_label_forms_match(line: str) -> None:
    (check,) = _amount(_facts_eur(), line)
    assert check.match and check.source_value.startswith("inbound.amount.EUR")


@pytest.mark.parametrize(
    "line",
    [
        "입금 합계는 62,992,819.39 유로(EUR)임.",  # 숫자 하나 다름
        "입금 합계는 6,299,281.938 유로(EUR)임.",  # 쉼표·자리 틀림 = 다른 값
        "입금 합계는 62,992,819.38 미국 달러(USD)임.",  # 통화 다름
    ],
)
def test_wrong_value_still_mismatch(line: str) -> None:
    (check,) = _amount(_facts_eur(), line)
    assert not check.match and check.reason is CheckReason.MISMATCH


def test_multi_currency_lines_each_matched() -> None:
    facts = Facts.model_validate(
        json.loads((FIXTURES / "facts_multi_currency.json").read_text(encoding="utf-8"))
    )
    lines = ["유로 입금 합계는 9,800.25 유로(EUR)임.", "미국 달러 입금 합계는 42,750.50 미국 달러(USD)임."]
    checks = [c for c in run_summary_code_checks(facts, lines, facts.inbound.transaction_ids)
              if c.check is CodeCheckName.AMOUNT_MATCH]  # fmt: skip
    assert len(checks) == 2 and all(c.match for c in checks)
