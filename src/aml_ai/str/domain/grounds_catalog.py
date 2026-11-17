"""사유 카탈로그 — GROUNDS 슬롯 뒤에 붙는 닫힌 문장 (docs/str/05 narrative_v4 "사유 카탈로그"). 순수.

항목 = id · 조건 · 우선순위 · 변형 · cites. `~이나`·`~인데`·`반면` 연결과 "어긋남" 판정은 쓰지 않는다.
조건이 거짓이면 항목이 빠질 뿐 — 자료를 지워도 문장이 더 세지지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aml_ai.str.domain.catalog_types import CatalogItem, holds, premises
from aml_ai.str.domain.typology_support import typology_support

NOT_CONFIRMED = "제공된 자료로 확인되지 않음."

GROUNDS_ITEMS: tuple[CatalogItem, ...] = (
    CatalogItem(
        "G-CYCLE-PATH",
        1,
        (
            f"자금 순환을 뒷받침하는 경로는 {NOT_CONFIRMED}",
            f"자금 순환을 뒷받침하는 경로가 있는지는 {NOT_CONFIRMED}",
        ),
        ("typology",),
        noun="자금 순환을 뒷받침하는 경로",  # "돌아온" 은 경로 확인(cycle_verified) 항목에만
    ),
    CatalogItem(
        "G-PURPOSE-IN",
        1,
        (
            f"계좌 목적은 {{purpose_ro}} 등록되어 있으며, 위 입금이 등록된 계좌 목적에 해당하는 거래인지는 {NOT_CONFIRMED}",
            f"위 입금이 계좌 목적으로 등록된 {{purpose}}에 해당하는 거래인지는 {NOT_CONFIRMED}",
            f"등록된 계좌 목적은 {{purpose_imyeo}}, 위 입금과 계좌 목적의 관계는 {NOT_CONFIRMED}",
        ),
        ("customer.account_purpose", "inbound.count"),
        noun="위 입금과 등록된 계좌 목적의 관계",
        requires=("has_purpose", "has_inbound"),
    ),
    CatalogItem(
        "G-PURPOSE-OUT",
        1,
        (
            "계좌 목적은 {purpose_ro} 등록되어 있음. 거래 기간 중 입금은 없고 출금만 있음.",
            "거래 기간 중 입금은 없고 출금만 있음. 계좌 목적은 {purpose_ro} 등록되어 있음.",
        ),
        ("customer.account_purpose", "inbound.count", "outbound.count"),
        requires=("has_purpose", "has_outbound"),
    ),
    CatalogItem(
        "G-COUNTERPARTY",
        2,
        (
            f"해당 상대 계좌와 대상자의 거래 관계는 {NOT_CONFIRMED}",
            f"대상자와 해당 상대 계좌가 어떤 거래 관계인지는 {NOT_CONFIRMED}",
            f"해당 상대 계좌가 대상자의 거래처인지는 {NOT_CONFIRMED}",
        ),
        ("counterparties.count",),
        noun="해당 상대 계좌와 대상자의 거래 관계",
        requires=("has_counterparty",),
    ),
    CatalogItem(
        "G-PRIOR",
        3,
        (
            f"과거 경보 이력이 있으며, 이번 거래와의 관련성은 {NOT_CONFIRMED}",
            f"과거 경보 이력과 이번 거래의 관련성은 {NOT_CONFIRMED}",
            f"이번 거래가 과거 경보와 어떤 관련이 있는지는 {NOT_CONFIRMED}",
        ),
        ("prior_alert_count",),
        noun="이번 거래와 과거 경보의 관련성",
        requires=("has_prior",),
    ),
)


# 전제(requires) 밖의 조건 — 전제는 catalog_types.premises 가 판정
_CONDITIONS: dict[str, Callable[[dict[str, Any], dict[str, bool]], bool]] = {
    # 경로 없음·UNVERIFIED·비순환 VERIFIED · 판정 문장 없을 때만(SCRUM-265 2/2 — 판정 미확인 문장과 같은 뜻)
    "G-CYCLE-PATH": lambda f, _: (
        f.get("typology") == "CYCLE" and not premises(f)["cycle_verified"] and typology_support(f) is None
    ),
    "G-PURPOSE-IN": lambda f, _: True,
    "G-PURPOSE-OUT": lambda f, flags: flags["outbound_only"],
    "G-COUNTERPARTY": lambda f, _: True,
    "G-PRIOR": lambda f, _: True,
}


def grounds_candidates(facts: dict[str, Any], flags: dict[str, bool]) -> list[CatalogItem]:
    """조건과 전제가 모두 참인 사유 항목 — 우선순위·id 순."""
    prem = premises(facts)
    items = [i for i in GROUNDS_ITEMS if _CONDITIONS[i.id](facts, flags) and holds(i, prem)]
    return sorted(items, key=lambda i: (i.priority, i.id))
