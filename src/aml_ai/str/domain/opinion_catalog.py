"""종합의견 카탈로그 — 유형별 첫 문장 + 확인 사항 (docs/str/05 narrative_v4 "종합의견 카탈로그"). 순수.

첫 문장은 필수(유형마다 하나). 확인 사항은 "〈사실〉이므로 〈확인할 것〉을 확인할 필요가 있음" 완성형,
필수(C1·C2)는 코드가 고정, 선택은 표 순서가 우선순위. 짝 사유 항목이 같이 나오면 짧은 꼴(05 "짝"). 면책 문장 없음.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aml_ai.str.domain.catalog_types import CatalogItem, holds, premises
from aml_ai.str.domain.constants_v4 import SALES_DEPOSIT
from aml_ai.str.domain.opinion_heads import HEADS, type_check_item

_NC = "제공된 자료로 확인되지 않으므로"


def _check(cid: str, variants: tuple[str, ...], cites: tuple[str, ...], **kw: Any) -> CatalogItem:
    return CatalogItem(cid, 0, variants, cites, **kw)


CHECK_ITEMS: tuple[CatalogItem, ...] = (
    _check(
        "C1",
        (
            "과거 경보 이력이 있으므로 이전 경보와 이번 거래의 관련성을 확인할 필요가 있음.",
            "이전 경보 이력이 있으므로 이번 거래와의 관련성을 확인할 필요가 있음.",
        ),
        ("prior_alert_count",),
        required=True,
        short="이전 경보와 이번 거래의 관련성을 확인할 필요가 있음.",
        pair="G-PRIOR",
        requires=("has_prior",),
    ),
    _check(
        "C2",
        (
            "고객 정보가 제공된 자료로 확인되지 않으므로 고객 확인 자료(업종·계좌 목적)를 보완할 필요가 있음.",
            "고객 확인 자료가 제공된 자료로 확인되지 않으므로 업종과 계좌 목적을 확인해 보완할 필요가 있음.",
        ),
        (),
        required=True,
    ),
    _check(
        "F1",
        (
            f"송금인 정보가 {_NC} 송금인과 대상자의 거래 관계를 확인할 필요가 있음.",
            f"송금인과 대상자의 거래 관계가 {_NC} 송금인 정보를 확인할 필요가 있음.",
        ),
        ("counterparties.count",),
        short="송금인과 대상자의 거래 관계를 확인할 필요가 있음.",
        pair="G-COUNTERPARTY",
        requires=("has_inbound", "has_counterparty"),
    ),
    _check(
        "F2",
        (
            "계좌 목적이 {purpose_ro} 등록되어 있으므로 위 입금에 대응하는 매출 증빙을 확인할 필요가 있음.",
            "등록된 계좌 목적이 {purpose_imeuro} 위 입금과 매출 증빙의 대응 여부를 확인할 필요가 있음.",
        ),
        ("customer.account_purpose",),
        requires=("has_inbound", "has_purpose"),
    ),
    _check(
        "F3",
        (
            f"위 입금의 이후 사용처가 {_NC} 이를 확인할 필요가 있음.",
            f"입금된 자금이 이후 어디에 쓰였는지 {_NC} 사용처를 확인할 필요가 있음.",
        ),
        ("inbound.count",),
        requires=("has_inbound",),
    ),
    _check(
        "O1",
        (
            f"수취인 정보가 {_NC} 수취인과 대상자의 거래 관계를 확인할 필요가 있음.",
            f"수취인과 대상자의 거래 관계가 {_NC} 수취인 정보를 확인할 필요가 있음.",
        ),
        ("counterparties.count",),
        short="수취인과 대상자의 거래 관계를 확인할 필요가 있음.",
        pair="G-COUNTERPARTY",
        requires=("has_outbound", "has_counterparty"),
    ),
    _check(
        "O2",
        (
            f"출금 전 자금이 들어온 경위가 {_NC} 직전 입금 내역을 확인할 필요가 있음.",
            f"위 출금에 쓰인 자금이 들어온 경위가 {_NC} 직전 입금 내역을 확인할 필요가 있음.",
        ),
        ("outbound.count",),
        requires=("has_outbound",),
    ),
    _check(
        "O3",
        (
            "계좌 목적이 {purpose_ro} 등록되어 있으므로 위 출금이 사업상 지급인지 근거 자료를 확인할 필요가 있음.",
            "등록된 계좌 목적이 {purpose_imeuro} 위 출금이 사업상 지급에 해당하는지 근거 자료를 확인할 필요가 있음.",
        ),
        ("customer.account_purpose", "outbound.count"),
        requires=("has_outbound", "has_purpose"),
    ),
    _check(
        "Y1",
        (
            f"경로상 계좌들과 대상자의 관계가 {_NC} 이를 확인할 필요가 있음.",
            f"경로에 나타난 계좌들과 대상자가 어떤 관계인지 {_NC} 이를 확인할 필요가 있음.",
        ),
        ("typology",),
        requires=("path_verified",),
    ),
    _check(
        "Y2",
        (
            f"자금이 출발 계좌로 돌아온 거래 목적이 {_NC} 이를 확인할 필요가 있음.",
            f"출발 계좌로 자금이 되돌아온 거래 목적이 {_NC} 이를 확인할 필요가 있음.",
        ),
        ("typology",),
        requires=("cycle_verified",),
    ),
    _check(
        "Y3",
        (
            f"자금 순환을 뒷받침하는 경로가 {_NC} 경로 확인 자료를 보완할 필요가 있음.",
            "제공된 자료로는 자금 순환을 뒷받침하는 경로가 확인되지 않으므로 경로 확인 자료를 보완할 필요가 있음.",
        ),
        ("typology",),
        short="경로 확인 자료를 보완할 필요가 있음.",
        pair="G-CYCLE-PATH",
    ),
    _check(
        "G1",
        (
            f"해당 상대 계좌와 대상자의 거래 관계가 {_NC} 이를 확인할 필요가 있음.",
            f"대상자와 해당 상대 계좌의 거래 관계가 {_NC} 이를 확인할 필요가 있음.",
        ),
        ("counterparties.count",),
        short="해당 상대 계좌와 대상자의 거래 관계를 확인할 필요가 있음.",
        pair="G-COUNTERPARTY",
        requires=("has_counterparty",),
    ),
    _check(
        "B1",
        (
            "상대 계좌 가운데 자행 계좌가 있으므로 해당 계좌의 고객 확인 자료를 함께 확인할 필요가 있음.",
            "상대 계좌에 자행 계좌가 있으므로 해당 계좌의 고객 확인 자료를 함께 확인할 필요가 있음.",
        ),
        ("counterparty_banks.same_bank_accounts",),
        requires=("has_same_bank",),
    ),
)

_KNOWN = ("FAN_IN", "FAN_OUT", "CYCLE")
# 전제(requires) 밖의 조건 — 전제는 catalog_types.premises 가 판정
_CONDITIONS: dict[str, Callable[[dict[str, Any], dict[str, bool]], bool]] = {
    "C1": lambda f, _: True,
    "C2": lambda f, _: f.get("customer") is None,
    "F1": lambda f, _: f.get("typology") == "FAN_IN",
    "F2": lambda f, _: f.get("typology") == "FAN_IN" and _purpose(f) == SALES_DEPOSIT,
    "F3": lambda f, flags: f.get("typology") == "FAN_IN" and flags["inbound_only"],
    "O1": lambda f, _: f.get("typology") == "FAN_OUT",
    "O2": lambda f, flags: f.get("typology") == "FAN_OUT" and flags["outbound_only"],
    "O3": lambda f, _: f.get("typology") == "FAN_OUT" and _purpose(f) == SALES_DEPOSIT,
    "Y1": lambda f, _: f.get("typology") == "CYCLE",
    "Y2": lambda f, _: f.get("typology") == "CYCLE",
    "Y3": lambda f, _: _cycle_unverified(f) and not premises(f)["typology_unsupported"],  # 뒷받침 안 됨 → C0
    "G1": lambda f, _: f.get("typology") not in _KNOWN,
    "B1": lambda f, _: True,
}


def _cycle_unverified(f: dict[str, Any]) -> bool:
    return f.get("typology") == "CYCLE" and not premises(f)["cycle_verified"]


def _purpose(f: dict[str, Any]) -> str | None:
    return (f.get("customer") or {}).get("account_purpose")


def opinion_head(facts: dict[str, Any]) -> CatalogItem:
    """유형별 첫 문장 — FAN_IN·FAN_OUT 은 그 방향 거래가 없으면 대상 낱말을 "위 거래"로(전제 없는 "위 입금" 금지)."""
    typology = facts.get("typology")
    if typology is None:
        return HEADS["NONE"]
    prem = premises(facts)
    if typology == "FAN_IN" and not prem["has_inbound"]:
        return HEADS["FAN_IN_NO_FLOW"]
    if typology == "FAN_OUT" and not prem["has_outbound"]:
        return HEADS["FAN_OUT_NO_FLOW"]
    return HEADS.get(typology, HEADS["OTHER"])


def opinion_candidates(facts: dict[str, Any], flags: dict[str, bool]) -> list[CatalogItem]:
    """조건과 전제가 모두 참인 확인 사항 — 표 순서(= 선택 우선순위)."""
    prem = premises(facts)
    c0 = type_check_item(facts)  # 뒷받침 안 됨이면 필수 C0 가 맨 앞(첫 문장 바로 뒤, SCRUM-265 2/2)
    return [
        *([c0] if c0 else []),
        *(c for c in CHECK_ITEMS if _CONDITIONS[c.id](facts, flags) and holds(c, prem)),
    ]
