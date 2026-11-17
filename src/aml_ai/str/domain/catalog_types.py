"""v4 카탈로그 항목 타입·렌더 (docs/str/05 narrative_v4 "사유 카탈로그"·"종합의견 카탈로그"). 순수.

카탈로그 문장은 닫힌 허용 목록이다 — 자유 문장 없음. 자리표시는 사전 표기만:
`{purpose}`·`{purpose_ro}`(으로/로)·`{purpose_imyeo}`(이며/며)·`{purpose_imeuro}`(이므로/므로)·`{typology}`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aml_ai.str.domain.display_format import with_imeuro, with_imyeo, with_ro
from aml_ai.str.domain.display_labels_check import Labels
from aml_ai.str.domain.typology_support import Support, typology_support


@dataclass(frozen=True)
class CatalogItem:
    id: str
    priority: int  # 작을수록 먼저(같으면 id 순)
    variants: tuple[str, ...]  # 뜻·cites 는 같고 어순·어휘만 다름
    cites: tuple[str, ...]
    required: bool = False  # 종합의견 필수 확인 사항(C1·C2)
    short: str | None = None  # 짝 사유 항목이 같은 초안에 있으면 이 꼴(05 "짝")
    pair: str | None = None  # 짝 사유 항목 id
    noun: str | None = None  # "확인 안 됨" 사유 항목의 명사구 — 둘 이상이면 한 문장으로 묶음(05 "묶기")
    # 문장이 깔고 있는 전제(constants_v4.PREMISES) — 하나라도 거짓이면 후보 아님
    requires: tuple[str, ...] = ()


def premises(facts: dict[str, Any]) -> dict[str, bool]:
    """전제 판정 — 마스킹본 기준(UNVERIFIED paths 는 이미 빠짐, 04)."""
    customer = facts.get("customer")
    paths = facts.get("paths")  # 마스킹본엔 VERIFIED 만 남음
    support = typology_support(facts)  # 판정 없는 유형이면 None — 아래 둘 다 거짓
    return {
        "has_inbound": facts["inbound"]["count"] > 0,
        "has_outbound": facts["outbound"]["count"] > 0,
        "has_counterparty": facts["counterparties"]["count"] > 0,
        "path_verified": paths is not None,
        "cycle_verified": paths is not None and paths.get("kind") == "CYCLE",  # 자금 복귀("돌아온")는 이것만
        "has_purpose": bool(customer) and customer.get("account_purpose") is not None,
        "has_customer": customer is not None,
        "has_prior": facts["prior_alert_count"] > 0,
        "has_same_bank": facts["counterparty_banks"]["same_bank_accounts"] > 0,
        "typology_supported": support is Support.SUPPORTED,
        "typology_unsupported": support in (Support.UNCONFIRMED, Support.UNMET),
    }


def holds(item: CatalogItem, prem: dict[str, bool]) -> bool:
    return all(prem[name] for name in item.requires)


def render_context(facts: dict[str, Any], labels: Labels) -> dict[str, str]:
    """자리표시 값 — 사전 표기에 조사만 붙인다. 값이 없으면 그 자리표시는 안 생김(쓰는 항목은 조건상 안 켜짐)."""
    ctx: dict[str, str] = {}
    customer = facts.get("customer") or {}
    purpose = customer.get("account_purpose")
    if purpose is not None:
        label = labels["account_purpose"][purpose]
        ctx |= {
            "purpose": label,
            "purpose_ro": with_ro(label),
            "purpose_imyeo": with_imyeo(label),
            "purpose_imeuro": with_imeuro(label),
        }
    typology = facts.get("typology")
    if typology is not None:
        ctx["typology"] = labels["typology"][typology]
    return ctx


def render(text: str, ctx: dict[str, str]) -> str:
    return text.format(**ctx)
