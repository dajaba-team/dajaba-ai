"""유형 뒷받침 판정 — 뒷받침됨·미확인·불충족 (docs/str/05 "유형 뒷받침 판정", 09 SCRUM-265 2/2 판정). 순수.

입력은 마스킹본 dict(UNVERIFIED paths 는 이미 빠짐 — 04). 식은 09 SCRUM-265 1/2 사전 등록 줄 ③:
송금인 하한 = counterparties − outbound, 상한 = min(inbound, counterparties)(수취인은 방향 반대).
상한 < 임계값 → 불충족 · 하한 ≥ 임계값 → 뒷받침됨 · 그 사이 → 미확인. 내부 거래 > 0 이면 불충족 → 미확인
(facts 셈은 내부 거래를 뺌 — 룰 셈과 다를 수 있음). 판정을 정의하지 않은 유형은 None.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from aml_ai.str.domain.constants_v4 import MIN_DISTINCT_RECEIVERS, MIN_DISTINCT_SENDERS, MIN_INTERMEDIATES


class Support(StrEnum):
    SUPPORTED = "SUPPORTED"  # 뒷받침됨
    UNCONFIRMED = "UNCONFIRMED"  # 미확인
    UNMET = "UNMET"  # 불충족


def sender_bounds(facts: dict[str, Any]) -> tuple[int, int]:
    cp = facts["counterparties"]["count"]
    return cp - facts["outbound"]["count"], min(facts["inbound"]["count"], cp)


def receiver_bounds(facts: dict[str, Any]) -> tuple[int, int]:
    cp = facts["counterparties"]["count"]
    return cp - facts["inbound"]["count"], min(facts["outbound"]["count"], cp)


def typology_support(facts: dict[str, Any]) -> Support | None:
    typology = facts.get("typology")
    if typology == "FAN_IN":
        return _by_bounds(sender_bounds(facts), MIN_DISTINCT_SENDERS, facts)
    if typology == "FAN_OUT":
        return _by_bounds(receiver_bounds(facts), MIN_DISTINCT_RECEIVERS, facts)
    paths = facts.get("paths")  # 마스킹본엔 VERIFIED 만
    if typology == "CYCLE":
        return (
            Support.SUPPORTED if paths is not None and paths.get("kind") == "CYCLE" else Support.UNCONFIRMED
        )
    if typology == "SCATTER_GATHER":
        ok = (
            paths is not None
            and paths.get("kind") == "SCATTER_GATHER"
            and paths["count"] >= MIN_INTERMEDIATES
        )
        return Support.SUPPORTED if ok else Support.UNCONFIRMED
    return None


def _by_bounds(bounds: tuple[int, int], threshold: int, facts: dict[str, Any]) -> Support:
    low, high = bounds
    if low >= threshold:
        return Support.SUPPORTED
    if high < threshold and facts["internal"]["count"] == 0:
        return Support.UNMET
    return Support.UNCONFIRMED
