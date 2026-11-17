"""유형 뒷받침 판정 문장 — GROUNDS 슬롯 맨 앞 · OPINION 확인 사항 C0 (docs/str/05 "유형 뒷받침 판정"·C0). 순수.

숫자·임계값 없음(06 COUNT 가 facts 와 대조), 인과·대립 연결어 없음. 판정 문장은 섹션 첫 등장이라 `{표기}({코드})`.
그 방향 거래가 0 이면 "위 입금"·"위 출금" 대신 "위 거래"(O-HEAD 와 같은 규칙).
"""

from __future__ import annotations

from typing import Any

from aml_ai.str.domain.display_format import label_with_code
from aml_ai.str.domain.display_labels_check import Labels
from aml_ai.str.domain.slot_types import SlotSentence, slot
from aml_ai.str.domain.typology_support import Support, typology_support

NOT_CONFIRMED = "제공된 자료로 확인되지 않음."
# 유형 → (방향 칸, 대상 낱말, 상대 낱말)
_FLOW = {"FAN_IN": ("inbound", "위 입금", "송금인"), "FAN_OUT": ("outbound", "위 출금", "수취인")}
_FLOW_CITES = ("typology", "counterparties.count", "inbound.count", "outbound.count")
# C0 — {typology} 는 사전 짧은 표기(render_context). GROUNDS 첫 문장이 이미 한계라 "확인되지 않으므로" 없음
C0_TEXT = {
    "FAN_IN": "{typology} 분류의 근거가 된 {target}을 확인할 필요가 있음.",
    "FAN_OUT": "{typology} 분류의 근거가 된 {target}을 확인할 필요가 있음.",
    "CYCLE": "경로 확인 자료를 보완할 필요가 있음.",
    "SCATTER_GATHER": "{typology} 분류의 근거가 된 중간 계좌 경로 자료를 보완할 필요가 있음.",
}
_C0_TARGET = {"FAN_IN": "송금인별 입금 내역", "FAN_OUT": "수취인별 출금 내역"}
NO_FLOW_TARGET = "거래 내역"


def support_sentence(facts: dict[str, Any], labels: Labels) -> SlotSentence | None:
    support = typology_support(facts)
    if support is None:
        return None
    typology = facts["typology"]
    name = label_with_code(labels["typology"][typology], typology)
    if typology in _FLOW:
        flow, target, party = _FLOW[typology]
        target = target if facts[flow]["count"] > 0 else "위 거래"
        text = {
            Support.SUPPORTED: f"{target}의 서로 다른 {party} 수는 {name} 유형의 탐지 기준을 충족함.",
            Support.UNMET: f"{target}의 서로 다른 {party} 수는 {name} 유형의 탐지 기준에 미치지 않음.",
            Support.UNCONFIRMED: f"{name} 분류를 뒷받침하는 서로 다른 {party} 수는 {NOT_CONFIRMED}",
        }[support]
        return slot(text, *_FLOW_CITES)
    if support is Support.SUPPORTED:
        return slot(f"확인된 경로는 {name} 분류와 부합함.", "typology", "paths.count")
    return slot(f"{name} 분류를 뒷받침하는 경로는 {NOT_CONFIRMED}", "typology")


def c0_template(facts: dict[str, Any]) -> str | None:
    """C0 문장 틀(자리표시 `{typology}`) — 뒷받침 안 됨일 때만. 그 방향 거래 0 이면 "거래 내역"."""
    typology = facts.get("typology")
    if typology not in C0_TEXT or typology_support(facts) in (None, Support.SUPPORTED):
        return None
    target = _C0_TARGET.get(typology, "")
    if typology in _FLOW and facts[_FLOW[typology][0]]["count"] == 0:
        target = NO_FLOW_TARGET
    return C0_TEXT[typology].replace("{target}", target)
