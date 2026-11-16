"""슬롯 생성기 — METHOD·GROUNDS·결제 방식 (docs/str/05 narrative_v4 "슬롯 생성기"). 순수.

통화·결제 방식은 섹션마다 첫 등장에만 `한글(코드)` 병기. 결제 방식 alias 가 없는 방식(`Bitcoin`)은
COUNT ⑥ 이 못 읽으므로 건수 없이 이름만(09 2026-11-17).
"""

from __future__ import annotations

from typing import Any

from aml_ai.str.domain.constants import PAYMENT_FORMAT_ALIASES
from aml_ai.str.domain.constants_v4 import FLOW_SCOPE
from aml_ai.str.domain.display_format import copula, label_with_code, money, obs_value, topic
from aml_ai.str.domain.display_labels_check import Labels
from aml_ai.str.domain.slot_types import SlotSentence, no_data, slot

_FLOW_WORD = {"inbound": "입금", "outbound": "출금"}


def payment_parts(facts: dict[str, Any], labels: Labels) -> tuple[list[str], list[str]]:
    """(`전신환(Wire) 2건` 조각들, cites)."""
    parts: list[str] = []
    cites: list[str] = []
    for p in facts.get("payment_format_counts", []):
        fmt = p["format"]
        name = label_with_code(labels["payment_format"][fmt], fmt)
        parts.append(f"{name} {p['count']:,}건" if fmt in PAYMENT_FORMAT_ALIASES else name)
        cites.append(f"payment_format_counts.{fmt}")
    return parts, cites


def flow_currencies(facts: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """(통화 코드, 그 통화 금액 fact 키들) — 코드순."""
    keys: dict[str, list[str]] = {}
    for flow in ("inbound", "outbound"):
        for c in facts[flow]["by_currency"]:
            keys.setdefault(c["currency"], []).append(f"{flow}.amount.{c['currency']}")
    return sorted(keys.items())


def method_slots(facts: dict[str, Any], labels: Labels) -> list[SlotSentence]:
    out: list[SlotSentence] = []
    typology = facts.get("typology")
    if typology is not None:
        name = label_with_code(labels["typology"][typology], typology)
        out.append(slot(f"{name} 유형으로 분류됨.", "typology"))
    counts = (
        f"입금은 {facts['inbound']['count']:,}건, 출금은 {facts['outbound']['count']:,}건, "
        f"내부 거래는 {facts['internal']['count']:,}건임."
    )
    out.append(slot(counts, "inbound.count", "outbound.count", "internal.count"))
    seen: set[str] = set()
    for flow in ("inbound", "outbound"):  # 방향마다 한 문장(05)
        rows = facts[flow]["by_currency"]
        if rows:
            amounts = ", ".join(f"{money(c['total'])} {_currency(c['currency'], labels, seen)}" for c in rows)
            text = f"{_FLOW_WORD[flow]} 합계는 {copula(amounts)}."
            out.append(slot(text, *(f"{flow}.amount.{c['currency']}" for c in rows)))
    for r in facts.get("amount_range", []):
        cur = _currency(r["currency"], labels, seen)
        short = labels["currency"][r["currency"]]
        text = f"{FLOW_SCOPE} 거래 금액은 최소 {money(r['min'])} {cur}, 최대 {money(r['max'])} {short}임."
        code = r["currency"]
        out.append(slot(text, f"amount_range.{code}.min", f"amount_range.{code}.max"))
    out += _path_slots(facts.get("paths"))
    return out


def _currency(code: str, labels: Labels, seen: set[str]) -> str:
    label = labels["currency"][code]
    if code in seen:
        return label
    seen.add(code)
    return label_with_code(label, code)


def _path_slots(paths: dict[str, Any] | None) -> list[SlotSentence]:
    """마스킹본에는 VERIFIED paths 만 남는다(04). 홉은 `홉` 단위(06 COUNT PATH_HOPS 전용)."""
    if paths is None:
        return []
    return [
        slot(f"확인된 경로는 {paths['count']:,}개임.", "paths.count"),
        slot(f"가장 긴 경로는 {paths['max_hops']:,}홉임.", "paths.max_hops"),
        slot(f"경로 하나가 거친 계좌는 최대 {paths['max_accounts']:,}개임.", "paths.max_accounts"),
    ]


def grounds_slots(facts: dict[str, Any], labels: Labels) -> list[SlotSentence]:
    observations = facts.get("observations", [])
    if not observations:
        return [no_data("모델 관측값")]
    # 부재 주장은 집계 전체를 볼 때만(05): 전부 None → 섹션 끝 한 문장, 일부만 None → 그 관측값 문장 안
    all_missing = all(o.get("baseline") is None for o in observations)
    out = [_observation(o, labels, mark_baseline=not all_missing) for o in observations]
    if all_missing:
        out.append(no_data("비교 기준값"))
    return out


def _window(start: str | None, end: str | None) -> str:
    """관측 구간 — 둘 다 있으면 범위, 한쪽만이면 "일부 자료 없음", 둘 다 없으면 "자료 없음"."""
    if start and end:
        return f"{start}~{end} 기준"
    if start or end:  # 날짜 없이 — 06 DATE 는 양 끝 다 있는 관측값만 대조, 괄호 안 쉼표는 COUNT 절을 나눔
        return "관측 구간 일부 자료 없음"
    return "관측 구간 자료 없음"


def _observation(o: dict[str, Any], labels: Labels, *, mark_baseline: bool) -> SlotSentence:
    window = _window(o.get("window_start"), o.get("window_end"))
    unit = labels["observation_unit"].get(o["unit"], "") if o.get("unit") else ""
    value = f"{obs_value(o['value'])}{unit}"
    basis = o.get("basis")
    head = f"모델 관측값({window})"
    if basis is None:
        text = f"{head}은 {copula(value)}. 관측 항목 이름은 자료 없음."  # 조사는 괄호 앞 `관측값` 기준
    else:
        text = f"{head}에서 {topic(labels['observation_basis'][basis])} {copula(value)}."
    if mark_baseline and o.get("baseline") is None:
        text += " 이 관측값의 비교 기준값은 자료 없음."
    return slot(text, f"observations.{o['name']}")
