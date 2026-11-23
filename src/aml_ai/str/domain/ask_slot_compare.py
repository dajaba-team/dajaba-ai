"""질문 답변 비교 자리표 — 대소는 코드가 (원칙 (B), docs/str/04 "답 자리표" · 06, SCRUM-362 B1). 순수 함수.

`compare.count` · `compare.amount.<C>`(그 통화가 두 방향 다 있을 때만 키가 있음) · 관측값 기준값 비교의 낱말(`winner`).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from aml_ai.str.domain.display_format import money


def compare_slot(rest: str, c: dict[str, Any]) -> tuple[str, str] | None:
    """비교 자리표(원칙 (B) — 대소는 코드가). `count` · `amount.<C>`(그 통화가 두 방향 다 있을 때만)."""
    if rest == "count":
        a, b = c["inbound"]["count"], c["outbound"]["count"]
        return "거래 건수 비교", f"입금 {a:,}건, 출금 {b:,}건 · {_flow_winner(a, b)}"
    kind, _, cur = rest.partition(".")
    if kind != "amount":
        return None
    a = next(r["total"] for r in c["inbound"]["by_currency"] if r["currency"] == cur)
    b = next(r["total"] for r in c["outbound"]["by_currency"] if r["currency"] == cur)
    return (
        f"{cur} 합계 비교",
        f"입금 {money(a)} {cur}, 출금 {money(b)} {cur} · {_flow_winner(Decimal(a), Decimal(b))}",
    )


def _flow_winner(a: Decimal | int, b: Decimal | int) -> str:
    return winner(a, b, "입금이 더 많음", "출금이 더 많음", "같음")


def winner(a: Decimal | float, b: Decimal | float, more: str, less: str, same: str) -> str:
    return more if a > b else less if a < b else same
