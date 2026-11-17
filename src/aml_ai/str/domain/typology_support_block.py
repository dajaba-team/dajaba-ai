"""judge_v4 판정 근거 블록 — 평가자 user 칸 `{{typology_support}}` (docs/str/06 "judge_v4", 09 SCRUM-268). 순수.

입력은 평가자에 주는 것과 같은 마스킹본 dict. 판정은 `typology_support` 를 그대로 부름(읽기만 — 함수·임계값 안 바꿈).
계좌번호·금액·이름은 넣지 않음. 판정이 없는 유형이면 None → 문자열 `(없음)`.
"""

from __future__ import annotations

import json
from typing import Any

from aml_ai.str.domain.constants_v4 import MIN_DISTINCT_RECEIVERS, MIN_DISTINCT_SENDERS, MIN_INTERMEDIATES
from aml_ai.str.domain.typology_support import receiver_bounds, sender_bounds, typology_support

SUPPORT_BLOCK_SLOT = "{{typology_support}}"
NO_BLOCK = "(없음)"
# 유형 → (센 것, 하한·상한 함수, 임계값)
_FLOW = {
    "FAN_IN": ("distinct_senders", sender_bounds, MIN_DISTINCT_SENDERS),
    "FAN_OUT": ("distinct_receivers", receiver_bounds, MIN_DISTINCT_RECEIVERS),
}


def support_block(facts: dict[str, Any]) -> dict[str, Any] | None:
    support = typology_support(facts)
    if support is None:
        return None
    typology = facts["typology"]
    block: dict[str, Any] = {"typology": typology, "support": support.value}
    if typology in _FLOW:
        counted, bounds, threshold = _FLOW[typology]
        low, high = bounds(facts)
        internal = facts["internal"]["count"]
        return block | {
            "counted": counted,
            "lower_bound": low,
            "upper_bound": high,
            "threshold": threshold,
            "internal_count": internal,
            # 상한도 임계값 미만이면 원래 불충족 — 내부 거래가 있어 미확인으로 내림(typology_support._by_bounds)
            "lowered_by_internal": low < threshold and high < threshold and internal > 0,
        }
    paths = facts.get("paths")  # 마스킹본엔 VERIFIED 만
    block |= {
        "verified_path_kind": paths.get("kind") if paths else None,
        "verified_path_count": paths["count"] if paths else 0,
    }
    if typology == "SCATTER_GATHER":
        block["threshold"] = MIN_INTERMEDIATES
    return block


def render_support_block(facts: dict[str, Any]) -> str:
    block = support_block(facts)
    return NO_BLOCK if block is None else json.dumps(block, ensure_ascii=False, indent=2)
