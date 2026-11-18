"""흐름 문장 — GROUNDS 둘째, 유형 뒷받침됨일 때만 (docs/str/05 "흐름 문장", 09 SCRUM-269 ★A-2). 순수.

판정 문장 바로 뒤 슬롯 자리(상위 3 자르기·"확인 안 됨" 묶기·순서 목록 밖). 숫자·임계값 없음 — 수는 PLACE·METHOD·
관측값 슬롯에 이미 있음. 대상 계좌가 CYCLE 출발·SG 도착 계좌라는 주장은 안 함(facts 로 못 앎).
"""

from __future__ import annotations

from typing import Any

from aml_ai.str.domain.catalog_types import CatalogItem, holds, premises
from aml_ai.str.domain.slot_types import SlotSentence, slot

FLOW_ITEMS: dict[str, CatalogItem] = {
    "FAN_IN": CatalogItem(
        "G-FLOW-FAN_IN",
        0,
        ("위 입금은 여러 송금인 계좌에서 대상 계좌로 들어온 자금임.",),
        ("typology", "counterparties.count", "inbound.count"),
        required=True,
        requires=("typology_supported", "has_inbound", "has_counterparty"),
    ),
    "FAN_OUT": CatalogItem(
        "G-FLOW-FAN_OUT",
        0,
        ("위 출금은 대상 계좌에서 여러 수취인 계좌로 나간 자금임.",),
        ("typology", "counterparties.count", "outbound.count"),
        required=True,
        requires=("typology_supported", "has_outbound", "has_counterparty"),
    ),
    "CYCLE": CatalogItem(
        "G-FLOW-CYCLE",
        0,
        ("확인된 경로에서 자금은 다른 계좌를 거쳐 출발 계좌로 돌아옴.",),
        ("typology", "paths.count"),
        required=True,
        requires=("typology_supported", "cycle_verified"),  # 자금 복귀는 cycle_verified 만(Y2 와 같은 규칙)
    ),
    "SCATTER_GATHER": CatalogItem(
        "G-FLOW-SCATTER_GATHER",
        0,
        ("확인된 경로에서 한 출발 계좌의 자금은 서로 다른 중간 계좌를 거쳐 한 도착 계좌로 모임.",),
        ("typology", "paths.count"),
        required=True,
        requires=("typology_supported", "path_verified"),
    ),
}


def flow_item(facts: dict[str, Any]) -> CatalogItem | None:
    """그 유형의 흐름 항목 — 전제가 하나라도 거짓이면 None(뒷받침 안 됨·판정 없음 → 0)."""
    item = FLOW_ITEMS.get(facts.get("typology") or "")
    return item if item is not None and holds(item, premises(facts)) else None


def flow_sentence(facts: dict[str, Any]) -> SlotSentence | None:
    item = flow_item(facts)
    return None if item is None else slot(item.variants[0], *item.cites)
