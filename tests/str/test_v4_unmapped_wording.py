"""SCRUM-265 (2/2) 추가 검토 2차 — 미등록 통화가 있을 때 통화 열거·방향별 합계의 범위 (docs/str/05 INSTRUMENT·METHOD). LLM·DB 0.

미등록 통화가 있으면 "거래 통화 가운데 대응이 확인된 통화는 …" · 그 방향만 "{입금/출금} 가운데 대응이 확인된 통화
거래의 합계는 …"(바로 뒤 "대응 미확인" 문장과 짝). 없으면 지금 문장 그대로. 변조는 06 이 잡아야 함.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import Facts, LlmNarrativeSection
from aml_ai.shared.schemas.str.narrative import SectionV2
from tests.str.facts_support import CASES, build
from tests.str.v4_catalog_lint import lint
from tests.str.v4_slot_support import assembled, failures

MIXED = CASES["mixed"]["transactions"]
CURRENCIES = "내부 거래를 뺀 입금·출금의 거래 통화 가운데 대응이 확인된 통화는 미국 달러(USD)임."
IN_TOTAL = "입금 가운데 대응이 확인된 통화 거래의 합계는 100.00 미국 달러(USD)임."


def _unmapped(row: dict, name: str = "Dogecoin") -> dict:
    out = dict(row)
    out.update(amount_paid="50.25", currency_paid=name, amount_received="50.25", currency_received=name)
    return out


def _texts(f: Facts) -> dict[SectionV2, str]:
    return {s.section: s.text for s in assembled(f)}


def _mutated(f: Facts, sec: SectionV2, old: str, new: str) -> list[LlmNarrativeSection]:
    out = []
    for s in assembled(f):
        if s.section is sec:
            assert old in s.text, (old, s.text)
            s = s.model_copy(update={"text": s.text.replace(old, new, 1)})
        out.append(s)
    return out


def test_inbound_unmapped_scopes_currency_list_and_inbound_total() -> None:
    f = build({"transactions": [MIXED[0], _unmapped(MIXED[1])]})  # USD 100.00 입금 + Dogecoin 50.25 입금
    t = _texts(f)
    assert (
        CURRENCIES in t[SectionV2.INSTRUMENT]
        and "Dogecoin 통화 거래는 대응 미확인임." in t[SectionV2.INSTRUMENT]
    )
    assert IN_TOTAL in t[SectionV2.METHOD] and "입금 합계는" not in t[SectionV2.METHOD]
    assert failures(f, assembled(f)) == []
    assert failures(f, _mutated(f, SectionV2.METHOD, "합계는 100.00 미국", "합계는 150.25 미국"))
    assert failures(
        f, _mutated(f, SectionV2.METHOD, "합계는 100.00 미국 달러(USD)", "합계는 100.00 유로(EUR)")
    )


def test_only_direction_with_unmapped_is_scoped() -> None:
    """미등록은 입금에만 — 출금 합계(USD 30.00)는 지금 문장 그대로."""
    f = build({"transactions": [MIXED[0], _unmapped(MIXED[1]), MIXED[2]]})
    m = _texts(f)[SectionV2.METHOD]
    assert "입금 가운데 대응이 확인된 통화 거래의 합계는" in m and "출금 합계는 30.00 미국 달러임." in m
    assert "출금 가운데 대응이" not in m
    assert failures(f, assembled(f)) == []


def test_outbound_unmapped_scopes_outbound_only() -> None:
    f = build({"transactions": [MIXED[0], _unmapped(MIXED[2])]})  # 출금이 미등록
    m = _texts(f)[SectionV2.METHOD]
    assert (
        "입금 합계는 100.00 미국 달러(USD)임." in m and "출금 가운데 대응이" not in m
    )  # 출금은 등록 통화 0 — 합계 문장 없음
    assert failures(f, assembled(f)) == []


def test_no_unmapped_keeps_current_sentences() -> None:
    f = build({"transactions": MIXED[:3]})
    t = _texts(f)
    assert "대응이 확인된" not in t[SectionV2.INSTRUMENT] + t[SectionV2.METHOD]
    assert "내부 거래를 뺀 입금·출금의 거래 통화는 " in t[SectionV2.INSTRUMENT]
    assert "입금 합계는 " in t[SectionV2.METHOD] and "출금 합계는 " in t[SectionV2.METHOD]


def test_scope_phrase_passes_lint() -> None:
    assert (
        lint("대응이 확인된 통화 거래의 합계임.") == []
        and lint("거래 통화 가운데 대응이 확인된 통화임.") == []
    )
