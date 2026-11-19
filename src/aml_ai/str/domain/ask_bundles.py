"""질문 답변 묶음 → 마스킹 facts 조각 + 인용 키 (docs/str/04 "질문 답변 묶음", SCRUM-290). 순수 함수.

조각은 `mask_for_llm` 결과에서만 꺼낸다 — 거래 ID·indirect·미확인 경로는 이미 빠져 있다.
인용 키는 이 케이스 `fact_keys(facts)` 중 고른 묶음에 속한 것만, `fact_keys` 순서 그대로.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from aml_ai.shared.schemas.str import Facts
from aml_ai.shared.schemas.str.ask_llm import AskBundle
from aml_ai.str.domain.display_labels_check import Labels
from aml_ai.str.domain.fact_keys import fact_keys
from aml_ai.str.domain.masking import mask_for_llm

B = AskBundle

_FIELDS: dict[AskBundle, tuple[str, ...]] = {
    B.SUBJECT: ("subject", "customer", "prior_alert_count", "reporting_institution"),
    B.FLOWS: (
        "period",
        "inbound",
        "outbound",
        "internal",
        "amount_range",
        "direction",
        "unmapped_currencies",
    ),
    B.COUNTERPARTIES: ("counterparties", "counterparty_banks"),
    B.FORMATS: ("payment_formats", "payment_format_counts", "direction"),
    B.PATHS: ("paths",),
    B.OBSERVATIONS: ("observations",),
    B.SCORE_REASONS: ("model_signals", "observations"),
    B.RULE_FACTS: ("typology", "typology_source", "period"),
}

# 관측 항목에서 남길 칸 — 두 묶음을 함께 고르면 합집합
_OBSERVATION_FIELDS: dict[AskBundle, tuple[str, ...]] = {
    B.OBSERVATIONS: ("name", "value", "unit", "window_start", "window_end", "basis"),
    B.SCORE_REASONS: ("name", "value", "unit", "baseline"),
}

# 인용 키 — (그대로 같은 키, 앞부분이 같은 키)
_KEY_RULES: dict[AskBundle, tuple[tuple[str, ...], tuple[str, ...]]] = {
    B.SUBJECT: (("subject", "prior_alert_count"), ("subject.", "customer.")),
    B.FLOWS: (
        ("period", "direction"),
        ("inbound.", "outbound.", "internal.", "amount_range.", "unmapped_currencies."),
    ),
    B.COUNTERPARTIES: ((), ("counterparties.", "counterparty_banks.")),
    B.FORMATS: (("payment_formats", "direction"), ("payment_format_counts.",)),
    B.PATHS: ((), ("paths.",)),
    B.OBSERVATIONS: ((), ("observations.",)),
    B.SCORE_REASONS: (("model_signals",), ("observations.",)),
    B.RULE_FACTS: (("typology", "period"), ()),
}


@dataclass(frozen=True)
class AskPiece:
    bundles: tuple[str, ...]
    content: dict[str, Any]  # 답 프롬프트에 가는 조각(마스킹본) + labels
    keys: tuple[str, ...]  # 인용할 수 있는 fact 키


def extract(facts: Facts, rule_id: str, bundles: Sequence[str], labels: Labels) -> AskPiece:
    """목록 밖 묶음 이름은 ValueError(AskBundle 변환). 같은 칸이 두 묶음에 걸려도 한 번만."""
    names = list(dict.fromkeys(AskBundle(b) for b in bundles))
    masked = mask_for_llm(facts)
    content: dict[str, Any] = {}
    for name in names:
        for field in _FIELDS[name]:
            if field in masked:
                content[field] = masked[field]
        if name is B.RULE_FACTS:
            content["rule_id"] = rule_id
    if "observations" in content:
        content["observations"] = _observations(content["observations"], names)
    picked_labels = _labels(content, labels)
    if picked_labels:
        content["labels"] = picked_labels
    keys = tuple(k for k in fact_keys(facts) if any(_cites(k, n) for n in names))
    return AskPiece(bundles=tuple(n.value for n in names), content=content, keys=keys)


def _observations(items: list[dict[str, Any]], names: list[AskBundle]) -> list[dict[str, Any]]:
    keep = {f for n in names for f in _OBSERVATION_FIELDS.get(n, ())}
    return [{k: v for k, v in item.items() if k in keep} for item in items]


def _cites(key: str, name: AskBundle) -> bool:
    exact, prefixes = _KEY_RULES[name]
    return key in exact or key.startswith(prefixes)


def _labels(content: dict[str, Any], labels: Labels) -> dict[str, dict[str, str]]:
    """조각에 나온 코드값의 한글 표기만. 통화는 주지 않는다(ISO 코드 그대로, 04)."""
    codes: dict[str, set[str]] = {}

    def add(field: str, value: Any) -> None:
        if isinstance(value, str):
            codes.setdefault(field, set()).add(value)

    add("entity_type", (content.get("subject") or {}).get("entity_type"))
    for field in ("industry", "risk_level", "account_purpose"):
        add(field, (content.get("customer") or {}).get(field))
    for fmt in content.get("payment_formats", []):
        add("payment_format", fmt)
    for item in content.get("payment_format_counts", []):
        add("payment_format", item["format"])
    add("typology", content.get("typology"))
    for obs in content.get("observations", []):
        add("observation_name", obs.get("name"))
        add("observation_unit", obs.get("unit"))
        add("observation_basis", obs.get("basis"))
    out: dict[str, dict[str, str]] = {}
    for field, values in codes.items():
        found = {v: labels[field][v] for v in sorted(values) if v in labels.get(field, {})}
        if found:
            out[field] = found
    return out
