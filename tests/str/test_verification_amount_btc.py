"""AMOUNT_MATCH BTC 소수 (SCRUM-140). 정본 docs/str/06 "허용 오차 0" 소수 3자리 예시.

facts_fan_in 복사본의 inbound 를 BTC 로 바꿔 소수 자릿수 비교를 본다. develop 의
`FactAmount` 패턴 `^\\d+\\.\\d{2}$` 은 `"0.0042"` 를 거부해 fixture 단계에서 실패하고,
브랜치는 `^\\d+\\.\\d{2,6}$` 라 통과 — Decimal 비교로 match / MISMATCH 로 가른다.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CheckReason, Facts, SectionV1
from tests.conftest import FIXTURES, load_json
from tests.str.verification_support import amount


def _facts_btc_total(total: str) -> Facts:
    data = load_json(FIXTURES / "facts_fan_in.json")
    base = data["inbound"]["by_currency"][0]
    data["inbound"]["by_currency"] = [
        {
            "currency": "BTC",
            "total": total,
            "count": base["count"],
            "transaction_ids": base["transaction_ids"],
        }
    ]
    data["amount_range"] = [{"currency": "BTC", "min": total, "max": total}]
    return Facts.model_validate(data)


def test_amount_match_btc_small_decimal_match() -> None:
    """facts `"0.0042"` + 본문 `"0.0042 BTC"` → match (Decimal 비교 — 코드 변경 없이 통과 기대)."""
    checks = amount(_facts_btc_total("0.0042"), SectionV1.SUMMARY, "입금 0.0042 BTC")
    assert checks and all(c.match for c in checks), [c for c in checks if not c.match]


def test_amount_match_btc_mismatch_when_truncated() -> None:
    """facts `"0.0042"` + 본문 `"0.004 BTC"` → MISMATCH (잘라 쓰면 안 맞게)."""
    checks = amount(_facts_btc_total("0.0042"), SectionV1.SUMMARY, "입금 0.004 BTC")
    assert checks and all(not c.match and c.reason is CheckReason.MISMATCH for c in checks)
