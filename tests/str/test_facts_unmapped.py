"""미등록 통화 보존 (SCRUM-47, 미결 7) — docs/str/04 `unmapped_currencies`.

커밋 1 — 표에 없는 통화 이름은 500 아니고 facts.unmapped_currencies 에 원문 보존.
`by_currency`·`amount_range`·통화 대조에는 섞지 않고, inbound/outbound `count`·`transaction_ids`
및 `counterparties` 에는 포함.
"""

from __future__ import annotations

from typing import Any

from tests.str.facts_support import CASES, build


def _mixed_with_unmapped(name: str = "Dogecoin") -> dict[str, Any]:
    """mixed 경보에 미등록 통화 inbound 1건을 끼운 샘플."""
    rows = [dict(r) for r in CASES["mixed"]["transactions"]]
    new_id = max(r["transaction_id"] for r in rows) + 1
    rows.append(
        {
            "transaction_id": new_id,
            "ts": "2022-09-02T23:00:00",
            "from_account_key": "030_X0000001",
            "to_account_key": CASES["subject"]["account_key"],
            "amount_paid": "1.00",
            "currency_paid": name,
            "amount_received": "1.00",
            "currency_received": name,
            "payment_format": "Wire",
            "is_self_transfer": False,
        }
    )
    return {"transactions": rows, "unmapped_id": new_id, "unmapped_name": name}


def test_unmapped_currency_preserved_as_original_name() -> None:
    """표에 없는 통화 이름은 500 아니고 `unmapped_currencies` 로 원문 보존."""
    sample = _mixed_with_unmapped()
    f = build({"transactions": sample["transactions"]})
    names = [u.name for u in f.unmapped_currencies]
    assert names == [sample["unmapped_name"]]
    u = f.unmapped_currencies[0]
    assert u.count == 1
    assert u.transaction_ids == [sample["unmapped_id"]]


def test_unmapped_currency_not_in_by_currency_or_total() -> None:
    """`by_currency` 금액 집계·대조에는 섞지 않는다 — 다른 통화 합계는 그대로."""
    base = build(CASES["mixed"])
    with_unmapped = build({"transactions": _mixed_with_unmapped()["transactions"]})
    assert with_unmapped.inbound.by_currency == base.inbound.by_currency
    assert all(c.currency != "Dogecoin" for c in with_unmapped.inbound.by_currency)


def test_unmapped_currency_included_in_flow_count_and_counterparties() -> None:
    """미등록 통화 거래도 inbound/outbound `count`·`transaction_ids`·`counterparties` 에는 포함."""
    sample = _mixed_with_unmapped()
    base = build(CASES["mixed"])
    f = build({"transactions": sample["transactions"]})
    assert f.inbound.count == base.inbound.count + 1
    assert sample["unmapped_id"] in f.inbound.transaction_ids
    assert f.counterparties.count == base.counterparties.count + 1


def test_unmapped_currency_transaction_ids_dropped_by_mask_for_llm() -> None:
    """NFR-DRF-03 — 마스킹 뒤 `unmapped_currencies[].transaction_ids` 는 사라져야(LLM 에 거래 ID 안 감)."""
    from aml_ai.str.domain.masking import mask_for_llm

    f = build({"transactions": _mixed_with_unmapped()["transactions"]})
    masked = mask_for_llm(f)
    assert masked["unmapped_currencies"]
    assert all("transaction_ids" not in u for u in masked["unmapped_currencies"])


def test_unmapped_currency_fact_key_evidence_ids() -> None:
    """`unmapped_currencies.{name}` fact 키 → 그 거래 ID. 금액 fact 키는 없음(서술에 금액 못 씀)."""
    from aml_ai.str.domain.fact_keys import fact_keys

    sample = _mixed_with_unmapped()
    f = build({"transactions": sample["transactions"]})
    keys = fact_keys(f)
    assert keys[f"unmapped_currencies.{sample['unmapped_name']}"] == [sample["unmapped_id"]]
    assert f"inbound.amount.{sample['unmapped_name']}" not in keys  # 금액 키 없음
