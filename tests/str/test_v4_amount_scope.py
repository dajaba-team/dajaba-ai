"""SCRUM-265 (2/2) 추가 검토 1차 — "거래 금액은 모두" 문장의 통화 범위 (docs/str/05 METHOD 슬롯). LLM·DB 0.

통화가 둘 이상이면 "…입금·출금 가운데 {통화} 거래의 금액은 모두 …"(다른 통화 거래까지 덮는 모순 문장 금지).
통화 하나면 지금 문장 그대로. 최소 ≠ 최대 문장은 그대로. 변조는 06 AMOUNT_MATCH 가 잡아야 함.
"""

from __future__ import annotations

import re

from aml_ai.shared.schemas.str import Facts, LlmNarrativeSection
from aml_ai.shared.schemas.str.narrative import SectionV2
from tests.str.facts_support import CASES, build
from tests.str.v4_slot_support import assembled, failures

MIXED = CASES["mixed"]["transactions"]
UNSCOPED = re.compile(r"입금·출금의 거래 금액은 모두")


def _facts(rows: list[dict]) -> Facts:
    return build({"transactions": rows})


def _method(f: Facts) -> str:
    return next(s.text for s in assembled(f) if s.section is SectionV2.METHOD)


def _mutated(f: Facts, old: str, new: str) -> list[LlmNarrativeSection]:
    out = []
    for s in assembled(f):
        if s.section is SectionV2.METHOD:
            assert old in s.text, (old, s.text)
            s = s.model_copy(update={"text": s.text.replace(old, new, 1)})
        out.append(s)
    return out


def test_mixed_two_currencies_each_scoped() -> None:
    """지적 재현 — EUR 50.25·USD 100.00(입금 둘): 범위 없는 "모두"가 두 번 나오지 않고 문장마다 자기 통화 범위."""
    f = _facts(MIXED[:2])
    m = _method(f)
    assert not UNSCOPED.search(m)
    assert "내부 거래를 뺀 입금·출금 가운데 유로 거래의 금액은 모두 50.25 유로임." in m
    assert "내부 거래를 뺀 입금·출금 가운데 미국 달러 거래의 금액은 모두 100.00 미국 달러임." in m
    assert failures(f, assembled(f)) == []


def test_one_currency_equal_other_range() -> None:
    """입금 USD 100.00·EUR 50.25 + 출금 USD 30.00(지급 통화) — EUR 만 최소 = 최대(범위 붙음), USD 는 최소·최대 그대로."""
    f = _facts(MIXED[:3])
    m = _method(f)
    assert "가운데 유로 거래의 금액은 모두 50.25 유로임." in m
    assert "거래 금액은 최소 30.00 미국 달러, 최대 100.00 미국 달러임." in m and not UNSCOPED.search(m)
    assert failures(f, assembled(f)) == []


def test_single_currency_keeps_plain_sentence() -> None:
    f = _facts(MIXED[:1])
    m = _method(f)
    assert "내부 거래를 뺀 입금·출금의 거래 금액은 모두 100.00 미국 달러임." in m and "가운데" not in m
    assert failures(f, assembled(f)) == []


def test_scoped_amount_swapped_to_other_currency_is_caught() -> None:
    f = _facts(MIXED[:2])
    eur = "가운데 유로 거래의 금액은 모두 50.25 유로임."
    assert failures(f, _mutated(f, eur, "가운데 유로 거래의 금액은 모두 100.00 유로임."))
    usd = "가운데 미국 달러 거래의 금액은 모두 100.00 미국 달러임."
    assert failures(f, _mutated(f, usd, "가운데 미국 달러 거래의 금액은 모두 50.25 미국 달러임."))
    assert failures(f, _mutated(f, eur, "가운데 유로 거래의 금액은 모두 50.25 미국 달러임."))  # 통화 바꿈


def test_scope_currency_word_does_not_pair_with_other_number() -> None:
    """숫자 없이 나오는 앞의 통화 낱말이 AMOUNT 결과를 따로 만들지 않음 — 금액 1개당 1줄."""
    from tests.str.v4_slot_support import code_checks

    f = _facts(MIXED[:2])
    amounts = [c for c in code_checks(f, assembled(f)) if c.check == "AMOUNT_MATCH" and c.section == "METHOD"]
    m = _method(f)
    numbers = re.findall(r"\d[\d,]*\.\d{2}", m)
    assert len(amounts) == len(numbers) and all(c.match for c in amounts)


def _unmapped(amount: str = "50.25", name: str = "Dogecoin") -> dict:
    """mixed 둘째 거래(입금)를 미등록 통화로 — 실제 거래 → build_facts."""
    row = dict(MIXED[1])
    row.update(amount_paid=amount, currency_paid=name, amount_received=amount, currency_received=name)
    return row


def test_one_registered_plus_unmapped_is_scoped() -> None:
    """추가 검토 2차 재현 — USD 100.00 + 미등록 50.25: amount_range 는 USD 하나뿐이어도 "모두"는 범위를 붙임."""
    f = _facts([MIXED[0], _unmapped()])
    assert len(f.amount_range) == 1 and [u.name for u in f.unmapped_currencies] == ["Dogecoin"]
    m = _method(f)
    assert not UNSCOPED.search(m)
    assert "내부 거래를 뺀 입금·출금 가운데 미국 달러 거래의 금액은 모두 100.00 미국 달러임." in m
    assert failures(f, assembled(f)) == []


def test_only_unmapped_has_no_all_sentence() -> None:
    f = _facts([_unmapped()])
    assert f.amount_range == [] and f.unmapped_currencies
    assert "모두" not in _method(f)
    assert failures(f, assembled(f)) == []
