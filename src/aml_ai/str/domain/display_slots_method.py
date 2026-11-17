"""슬롯 생성기 — METHOD·GROUNDS·결제 방식 (docs/str/05 narrative_v4 "슬롯 생성기"). 순수.

통화·결제 방식은 섹션마다 첫 등장에만 `한글(코드)` 병기. 결제 방식 alias 가 없는 방식(`Bitcoin`)은
COUNT ⑥ 이 못 읽으므로 건수 없이 이름만(09 2026-11-17).
"""

from __future__ import annotations

from typing import Any

from aml_ai.str.domain.constants import PAYMENT_FORMAT_ALIASES
from aml_ai.str.domain.constants_v4 import FLOW_SCOPE, FLOW_SCOPE_BARE, MAPPED_SCOPE
from aml_ai.str.domain.display_format import copula, label_with_code, money, obs_value, topic_before_paren
from aml_ai.str.domain.display_labels_check import Labels
from aml_ai.str.domain.slot_types import SlotSentence, no_data, slot

_FLOW_WORD = {"inbound": "입금", "outbound": "출금"}


NO_OBSERVATION = "점수를 높인 모델 관측값은 제공된 자료로 확인되지 않음."
NO_WINDOW_NO_BASELINE = "모델 관측값의 관측 구간과 비교 기준값은 제공된 자료로 확인되지 않음."


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
            # 그 방향에 미등록 통화 거래가 있으면(count > 등록 통화 건수 합) 합계 범위를 밝힘(추가 검토 2차)
            unmapped = facts[flow]["count"] > sum(c["count"] for c in rows)
            word = f"{_FLOW_WORD[flow]} 가운데 {MAPPED_SCOPE} 거래의" if unmapped else _FLOW_WORD[flow]
            text = f"{word} 합계는 {copula(amounts)}."
            out.append(slot(text, *(f"{flow}.amount.{c['currency']}" for c in rows)))
    # 통화 종류 = 등록(amount_range) + 미등록 — 미등록도 다른 통화로 셈(추가 검토 2차)
    multi = len(facts.get("amount_range", [])) + len(facts.get("unmapped_currencies", [])) > 1
    for r in facts.get("amount_range", []):
        cur = _currency(r["currency"], labels, seen)
        short = labels["currency"][r["currency"]]
        text = f"{FLOW_SCOPE} 거래 금액은 최소 {money(r['min'])} {cur}, 최대 {money(r['max'])} {short}임."
        if r["min"] == r["max"]:  # 같으면 "최소 X, 최대 X" 대신(SCRUM-265 2/2)
            # 통화가 둘 이상이면 그 통화 거래로 범위를 좁힘 — "모두"가 다른 통화까지 덮지 않게(추가 검토 1·2차)
            subject = f"{FLOW_SCOPE_BARE} 가운데 {short} 거래의 금액" if multi else f"{FLOW_SCOPE} 거래 금액"
            text = f"{subject}은 모두 {money(r['min'])} {cur}임."
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
    if not observations:  # reasons 없음·전부 걸러짐을 facts 로 구분 못 함 — 둘 다 참인 문장(SCRUM-265 2/2)
        return [slot(NO_OBSERVATION)]
    # 부재 주장은 집계 전체를 볼 때만(05): 전부 None → 섹션 끝 한 문장, 일부만 None → 그 관측값 문장 안
    all_missing = all(o.get("baseline") is None for o in observations)
    no_window = all(not o.get("window_start") and not o.get("window_end") for o in observations)
    same_window = len({(o.get("window_start"), o.get("window_end")) for o in observations}) == 1
    out = [
        _observation(
            o, labels, mark_baseline=not all_missing, window=not no_window, short=same_window and n > 0
        )
        for n, o in enumerate(observations)
    ]
    if no_window and all_missing:  # 둘 다 전부 null 일 때만 한 문장(SCRUM-265 2/2)
        return [*out, slot(NO_WINDOW_NO_BASELINE)]
    if no_window:  # 실제 reasons 형식(SCRUM-264) — 관측값마다 반복하지 않고 섹션 끝 한 번
        out.append(no_data("모델 관측값의 관측 구간"))
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


def _observation(
    o: dict[str, Any], labels: Labels, *, mark_baseline: bool, window: bool, short: bool = False
) -> SlotSentence:
    """표기·단위는 피처 이름 기준(SCRUM-264 — 실제 basis 는 늘 `model_feature`, unit null). 값은 환산 안 함.

    short — 모든 관측값 window 가 같을 때 둘째부터 `{표기} 관측값은 {값}임.`(관측 단어는 절마다 남김 — 06 COUNT)."""
    name = o["name"]
    value = f"{obs_value(o['value'])}{labels['observation_name_unit'][name]}"
    head = f"모델 관측값({_window(o.get('window_start'), o.get('window_end'))})" if window else "모델 관측값"
    text = f"{head}에서 {topic_before_paren(labels['observation_name'][name])} {copula(value)}."
    if short:
        text = f"{labels['observation_name'][name]} 관측값은 {copula(value)}."
    if mark_baseline and o.get("baseline") is None:
        text += " 이 관측값의 비교 기준값은 자료 없음."
    return slot(text, f"observations.{o['name']}")
