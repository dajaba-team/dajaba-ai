"""facts 확장 (SCRUM-47, 안건 6-2) — docs/str/04 새 칸 4개.

커밋 2 — `subject.entity_type` · `counterparty_banks` · `payment_format_counts` · `amount_range`.
규칙 표 한 줄 = 테스트 하나(docs/str/04 "단위 테스트" 절). self-transfer 제외·미등록 통화 제외는
공용 분류 규칙이라 각 테스트에서 재확인.
"""

from __future__ import annotations

from decimal import Decimal

from aml_ai.str.domain.fact_keys import fact_keys
from tests.str.facts_support import CASES, build, make_subject
from tests.str.test_facts_unmapped import _mixed_with_unmapped

_SUBJECT_KEY = CASES["subject"]["account_key"]


def _directional_rows() -> list[dict[str, object]]:
    """inbound 2건·outbound 1건 — 방향별 금액(received/paid)이 다른 환전 거래."""
    return [
        _tx(1001, "020_A0000001", _SUBJECT_KEY, "999.00", "USD", "100.00", "USD", "ACH"),
        _tx(1002, "020_A0000002", _SUBJECT_KEY, "888.00", "USD", "500.00", "USD", "ACH"),
        _tx(1003, _SUBJECT_KEY, "020_A0000003", "250.00", "USD", "777.00", "USD", "Wire"),
    ]


def _tx(
    tid: int,
    frm: str,
    to: str,
    paid: str,
    cur_paid: str,
    recv: str,
    cur_recv: str,
    fmt: str,
) -> dict[str, object]:
    return {
        "transaction_id": tid,
        "ts": "2022-09-02T10:00:00",
        "from_account_key": frm,
        "to_account_key": to,
        "amount_paid": paid,
        "currency_paid": cur_paid,
        "amount_received": recv,
        "currency_received": cur_recv,
        "payment_format": fmt,
        "is_self_transfer": False,
    }


# ---------- subject.entity_type ----------


def test_subject_entity_type_passes_through_when_present() -> None:
    """`subject.entity_type` 은 ops 원값 그대로(6종) — 서식 변환 금지."""
    f = build(CASES["mixed"], subject=make_subject(entity_type="SOLE_PROPRIETORSHIP"))
    assert f.subject.entity_type is not None
    assert f.subject.entity_type.value == "SOLE_PROPRIETORSHIP"


def test_subject_entity_type_null_when_absent() -> None:
    """`subject.entity_type` 이 없으면 null — null 이면 fact 키도 생기지 않는다(04)."""
    f = build(CASES["mixed"])
    assert f.subject.entity_type is None
    assert "subject.entity_type" not in fact_keys(f)


# ---------- counterparty_banks ----------


def test_counterparty_banks_splits_by_bank_id() -> None:
    """`account_key` 의 `{bank_id}` 가 대상과 같으면 same, 다르면 other.

    `mixed` 픽스처 상대는 전부 다른 bank_id(020·030) → 전부 other.
    """
    f = build(CASES["mixed"])
    assert f.counterparty_banks.same_bank_accounts == 0
    assert f.counterparty_banks.other_bank_accounts == f.counterparties.count


def test_counterparty_banks_includes_same_bank_when_present() -> None:
    """자행 상대가 있으면 same 로 분류 — 상대 account_key 를 S 와 같은 bank_id 로 바꾼 샘플."""
    rows = [dict(r) for r in CASES["mixed"]["transactions"]]
    s_bank = _SUBJECT_KEY.partition("_")[0]
    for r in rows:
        if r["from_account_key"] != _SUBJECT_KEY and not r.get("is_self_transfer"):
            r["from_account_key"] = f"{s_bank}_SAME99999"
            break
    f = build({"transactions": rows})
    assert f.counterparty_banks.same_bank_accounts >= 1
    assert (
        f.counterparty_banks.same_bank_accounts + f.counterparty_banks.other_bank_accounts
        == f.counterparties.count
    )


# ---------- payment_format_counts ----------


def test_payment_format_counts_order_by_count_desc_then_name() -> None:
    """건수 내림차순 → 이름순(동률 안정). 합계 = flow count 전체."""
    f = build(CASES["mixed"])
    pfc = f.payment_format_counts
    sorted_pfc = sorted(pfc, key=lambda p: (-p.count, p.format))
    assert pfc == sorted_pfc
    assert sum(p.count for p in pfc) == f.inbound.count + f.outbound.count


# ---------- amount_range ----------


def test_amount_range_per_currency_min_max() -> None:
    """통화별 min/max 가 통화별로 따로 — 통화 간 비교·합산 없음, 통화 코드 정렬."""
    f = build(CASES["mixed"])
    assert len(f.amount_range) >= 1
    currencies = [a.currency for a in f.amount_range]
    assert currencies == sorted(currencies)
    for a in f.amount_range:
        assert Decimal(a.min) <= Decimal(a.max)


def test_amount_range_excludes_unmapped_currency() -> None:
    """미등록 통화 제외 — 매핑 통화 min/max 는 base 와 같다."""
    sample = _mixed_with_unmapped()
    base = build(CASES["mixed"])
    f = build({"transactions": sample["transactions"]})
    assert all(a.currency != sample["unmapped_name"] for a in f.amount_range)
    assert {(a.currency, a.min, a.max) for a in f.amount_range} == {
        (a.currency, a.min, a.max) for a in base.amount_range
    }


def test_amount_range_uses_direction_amount() -> None:
    """거래마다 그 방향 금액 기준 — 입금 amount_received, 출금 amount_paid.

    inbound amount_paid·outbound amount_received 는 환전 거래라 다를 수 있음 — 보지 않는다.
    inbound amount_received {100, 500} + outbound amount_paid {250} → min=100, max=500.
    """
    f = build({"transactions": _directional_rows()})
    usd = next(a for a in f.amount_range if a.currency == "USD")
    assert Decimal(usd.min) == Decimal("100.00")
    assert Decimal(usd.max) == Decimal("500.00")


# ---------- fact 키 ----------


def test_new_fact_keys_present() -> None:
    """새 칸의 fact 키가 생성됨 — counterparty_banks·payment_format_counts·amount_range."""
    f = build(CASES["mixed"], subject=make_subject(entity_type="CORPORATION"))
    keys = fact_keys(f)
    assert keys.get("subject.entity_type") == []
    assert "counterparty_banks.same_bank_accounts" in keys
    assert "counterparty_banks.other_bank_accounts" in keys
    for p in f.payment_format_counts:
        assert f"payment_format_counts.{p.format}" in keys
    for a in f.amount_range:
        assert f"amount_range.{a.currency}.min" in keys
        assert f"amount_range.{a.currency}.max" in keys
