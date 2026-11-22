"""요약 LLM 입력 금액 표기 — `62,992,819.38 유로(EUR)` 완성 문자열 (SCRUM-340, docs/str/05 summary_v2). 순수.

LLM 에 보내는 복사본(`mask_for_llm` 결과 dict)의 금액 칸만 바꾼다 — `inbound`·`outbound` 의 `by_currency[].total`,
`amount_range[].min`·`max`(facts 에서 `_money` 로 만드는 금액 칸 전부). 원본 Facts·검사·저장은 그대로.
정수부 쉼표는 초안과 같은 `display_format.money`, 통화 이름은 표기 사전 `currency`. 새 숫자를 만들지 않는다.
"""

from __future__ import annotations

import copy
from typing import Any

from aml_ai.str.domain.display_format import label_with_code, money
from aml_ai.str.domain.display_labels_check import Labels

_FLOWS = ("inbound", "outbound")


def display_amount(amount: str, code: str, labels: Labels) -> str:
    """`62992819.38`·`EUR` → `62,992,819.38 유로(EUR)`. 사전에 없는 코드면 `62,992,819.38 EUR`."""
    label = labels.get("currency", {}).get(code)
    return f"{money(amount)} {label_with_code(label, code) if label else code}"


def with_display_amounts(facts_llm: dict[str, Any], labels: Labels) -> tuple[dict[str, Any], list[str]]:
    """(금액 칸을 바꾼 새 dict, 표기 사전에 없던 통화 코드 — 나온 순서·중복 없음). 입력 dict 는 안 바꿈."""
    out = copy.deepcopy(facts_llm)
    missing: list[str] = []

    def show(amount: str, code: str) -> str:
        if code not in labels.get("currency", {}) and code not in missing:
            missing.append(code)
        return display_amount(amount, code, labels)

    for flow in _FLOWS:
        for row in (out.get(flow) or {}).get("by_currency", []):
            row["total"] = show(row["total"], row["currency"])
    for rng in out.get("amount_range", []):
        rng["min"], rng["max"] = show(rng["min"], rng["currency"]), show(rng["max"], rng["currency"])
    return out, missing


# 금액 칸을 미리 표기해 넣는 요약 프롬프트(검토 1 M4) — 밖의 버전(summary_v1)은 develop 과 같은 입력
DISPLAY_AMOUNT_PROMPTS = frozenset({"summary_v2"})


def uses_display_amounts(prompt: str) -> bool:
    return prompt in DISPLAY_AMOUNT_PROMPTS


def llm_amounts(
    prompt: str, facts_llm: dict[str, Any], labels: Labels | None
) -> tuple[dict[str, Any], list[str]]:
    """버전별 — 표기 버전이면 `with_display_amounts`(사전 필수), 아니면 입력 그대로(사전 안 씀, 검토 2 M6)."""
    if not uses_display_amounts(prompt):
        return facts_llm, []
    if labels is None:
        raise ValueError(f"{prompt} needs display labels")
    return with_display_amounts(facts_llm, labels)
