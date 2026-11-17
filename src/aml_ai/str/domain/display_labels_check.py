"""표기 사전 빈 값 검사 — facts(마스킹본)에 나온 코드값이 사전에 다 있는지 (docs/str/05 narrative_v4 "표기 사전"). 순수.

없는 코드값은 LLM 호출 전에 생성 실패로(조용히 원문 코드를 본문에 내보내지 않음). null 은 사전을 안 거친다.
"""

from __future__ import annotations

from typing import Any

Labels = dict[str, dict[str, str]]


def used_codes(facts: dict[str, Any]) -> list[tuple[str, str]]:
    """(사전 칸, 코드값) — 슬롯이 표기로 바꿀 값 전부, 나온 순서·중복 제거."""
    found: list[tuple[str, str]] = []
    subject = facts.get("subject") or {}
    found.append(("entity_type", subject.get("entity_type")))
    customer = facts.get("customer") or {}
    for field in ("industry", "risk_level", "account_purpose"):
        found.append((field, customer.get(field)))
    found += [("payment_format", p["format"]) for p in facts.get("payment_format_counts", [])]
    found.append(("typology", facts.get("typology")))
    for flow in ("inbound", "outbound"):
        found += [("currency", c["currency"]) for c in facts[flow]["by_currency"]]
    found += [("currency", a["currency"]) for a in facts.get("amount_range", [])]
    for o in facts.get("observations", []):
        found += [
            ("observation_name", o["name"]),
            ("observation_name_unit", o["name"]),
        ]  # SCRUM-264 이름 기준
    return list(dict.fromkeys((f, c) for f, c in found if c is not None))


def missing_labels(facts: dict[str, Any], labels: Labels) -> list[tuple[str, str]]:
    """사전에 없는 (칸, 코드값). 비면 통과."""
    return [(f, c) for f, c in used_codes(facts) if c not in labels.get(f, {})]
