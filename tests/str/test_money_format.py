"""`_money` 포맷·build_facts 스케일 보존 — SCRUM-140 (docs/str/04 "금액 문자열 규칙").

scale 중립: Decimal('42750.50') 과 Decimal('42750.500000') 이 같은 '42750.50' 을 만든다.
ops_seed.sql 이 numeric(20,6) 로 바뀌면 fixture 금액이 전부 scale -6 으로 들어오므로 꼭 봐야 한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain import facts as facts_domain
from tests.str.facts_support import CASES, make_req, make_subject, make_txs

# ---------- _money 포맷 (문자열 함수 직접) ----------


@pytest.mark.parametrize(
    ("inp", "want"),
    [
        # 법정 통화 2자리 — 양쪽 scale 쌍이 같은 결과
        ("42750.50", "42750.50"),
        ("42750.500000", "42750.50"),  # scale -6 (DB numeric(20,6) 입력)
        ("320000000", "320000000.00"),
        ("320000000.000000", "320000000.00"),
        # BTC 중간 자릿수 — 끝 0 제거 후 최소 2자리 보장
        ("0.0042", "0.0042"),
        ("0.004200", "0.0042"),
        # BTC 1 sat
        ("0.000001", "0.000001"),
        # 0 경계
        ("0", "0.00"),
        ("0.5", "0.50"),
    ],
)
def test_money_vector(inp: str, want: str) -> None:
    assert facts_domain._money(Decimal(inp)) == want


# ---------- 6자리 방어선 (ROUND_HALF_EVEN) ----------


@pytest.mark.parametrize(
    ("inp", "want"),
    [
        ("0.0000004", "0.00"),  # 6자리 scale 로 반올림 → 0.000000 → '0.00'
        ("0.0000005", "0.00"),  # HALF_EVEN — 아래 자리가 0 짝수라 내림
        ("0.0000015", "0.000002"),  # HALF_EVEN — 아래 자리가 1 홀수라 올림
    ],
)
def test_money_boundary_rounding(inp: str, want: str) -> None:
    assert facts_domain._money(Decimal(inp)) == want


# ---------- facts build 경로 — DB numeric(20,6) scale -6 입력 ----------


def _row(
    tx_id: int,
    *,
    to_key: str,
    amount: str,
    currency: str,
) -> dict[str, Any]:
    return {
        "transaction_id": tx_id,
        "ts": "2022-09-02T10:00:00",
        "from_account_key": "020_A0000001",
        "to_account_key": to_key,
        "amount_paid": amount,
        "currency_paid": currency,
        "amount_received": amount,
        "currency_received": currency,
        "payment_format": "ACH",
        "is_self_transfer": False,
    }


def _build(rows: list[dict[str, Any]]) -> Facts:
    req = make_req(rows)
    return facts_domain.build_facts(req.to_facts_input(), make_txs(rows), make_subject())


def test_build_facts_legal_currency_scale_six_stays_two_digits() -> None:
    """합계가 scale -6 Decimal 로 들어와도 법정 통화는 `"42750.50"` (2자리) — SCRUM-140 핵심."""
    subject_key = CASES["subject"]["account_key"]
    rows = [_row(1, to_key=subject_key, amount="42750.500000", currency="US Dollar")]
    f = _build(rows)
    assert f.inbound.by_currency[0].currency == "USD"
    assert f.inbound.by_currency[0].total == "42750.50"
    assert f.amount_range[0].min == "42750.50"
    assert f.amount_range[0].max == "42750.50"


def test_build_facts_btc_small_decimal_not_truncated_to_zero() -> None:
    """BTC `0.004200` 이 facts `by_currency.total == "0.0042"` 로 살아남는지 — SCRUM-140 이유."""
    subject_key = CASES["subject"]["account_key"]
    rows = [_row(1, to_key=subject_key, amount="0.004200", currency="Bitcoin")]
    f = _build(rows)
    assert f.inbound.by_currency[0].currency == "BTC"
    assert f.inbound.by_currency[0].total == "0.0042"
    assert f.amount_range[0].min == "0.0042"
    assert f.amount_range[0].max == "0.0042"
