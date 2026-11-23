"""질문 답변 자리표 이름표 — fact 키 → (이름표, 값 표기) (docs/str/04 "답 자리표" 표, SCRUM-362). 순수 함수.

값은 묶음 조각(`AskPiece.content`, 마스킹본)에서만 꺼낸다. 표기는 초안 v4 슬롯 도우미(`display_format`) 그대로 —
쉼표·날짜 모양만, 합산·환산·반올림 없음. 이름표·값을 못 찾으면 None(자리표 오류, 06).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from aml_ai.str.domain.ask_slot_compare import compare_slot, winner
from aml_ai.str.domain.ask_slot_direction import direction_label
from aml_ai.str.domain.ask_slot_scope import scoped_value
from aml_ai.str.domain.display_format import ko_date, ko_datetime, label_with_code, money, obs_value
from aml_ai.str.domain.display_labels_check import Labels

Slot = tuple[str, str]  # (이름표, 값 표기) — 렌더링은 "이름표 값"

_FLOW = {"inbound": "입금", "outbound": "출금"}
_BANK = {"same_bank_accounts": "자행", "other_bank_accounts": "타행"}
# INBOUND·OUTBOUND 는 2배 이상 우세(04 `_direction`) — "만" 은 반대 방향 0건이 조각에서 확인될 때만(추가 검토 1 H1)
_EXTREME = {"max": "최대", "min": "최소"}
_PATH = {
    "count": ("확인된 경로", "개"),
    "max_hops": ("경로 최대", "단계"),
    "max_accounts": ("경로 하나가 거친 계좌 최대", "개"),
}
_CUSTOMER = {"industry": "업종", "risk_level": "고객 위험등급", "account_purpose": "계좌 목적"}


def slot(
    key: str,
    content: dict[str, Any],
    labels: Labels,
    *,
    exclusive_ok: bool = False,
    non_external: int = 0,
    evidence_scoped: bool = False,
) -> Slot | None:
    """키 하나의 (이름표, 값). 표에 없는 키·조각에 없는 값·표기 사전에 없는 코드는 None.

    `exclusive_ok` — 근거가 경보 전체이고 소유 정보가 있을 때만 배타·부재 방향 이름표(추가 검토 3 H3).
    `non_external` — 근거 중 내부·간접 거래 수 — 있으면 결제 방식 자리표 값 없음(추가 검토 3 H1)·대외 값 표시(★B8 N-2).
    `evidence_scoped` — 근거가 경보 전체로 확인되지 않음 — 근거 거래로 센 값 표시(★B8 N-1).
    """
    if non_external and key.startswith(("payment_formats", "payment_format_counts.")):
        return None
    try:
        pair = _slot(key, content, labels, exclusive_ok)
    except (KeyError, IndexError, TypeError, ValueError, StopIteration):
        return None
    if pair is None:
        return None
    return pair[0], scoped_value(key, pair[1], evidence_scoped=evidence_scoped, non_external=non_external)


def _slot(key: str, c: dict[str, Any], labels: Labels, exclusive_ok: bool = False) -> Slot | None:
    head, _, rest = key.partition(".")
    if head in _FLOW:
        return _flow(head, rest, c[head])
    if head == "internal" and rest == "count":
        return "내부 거래", f"{c['internal']['count']:,}건"
    if head == "amount_range":
        cur, _, which = rest.rpartition(".")
        row = next(r for r in c["amount_range"] if r["currency"] == cur)
        return f"입출금 중 {_EXTREME[which]} 거래 금액", f"{money(row[which])} {cur}"
    if head in ("counterparties", "counterparty_banks", "counterparties_by_direction"):
        return _counterparty(head, rest, c)
    if head in ("payment_format_counts", "payment_formats", "direction", "unmapped_currencies"):
        return _format(head, rest, c, labels, exclusive_ok)
    if head in ("subject", "customer", "prior_alert_count"):
        return _who(head, rest, c, labels)
    if head == "compare":
        return compare_slot(rest, c)
    if head in ("period", "typology", "paths", "observations", "model_signals"):
        return _case(head, rest, c, labels)
    return None


def _flow(side: str, rest: str, flow: dict[str, Any]) -> Slot | None:
    word = _FLOW[side]
    if rest == "count":
        return f"{word} 거래", f"{flow['count']:,}건"
    kind, _, cur = rest.partition(".")
    if kind != "amount":
        return None
    row = next(r for r in flow["by_currency"] if r["currency"] == cur)
    return f"{word} 합계", f"{money(row['total'])} {cur}"


def _counterparty(head: str, rest: str, c: dict[str, Any]) -> Slot | None:
    if head == "counterparties" and rest == "count":
        return "입출금 전체 상대 계좌", f"{c['counterparties']['count']:,}개"
    if head == "counterparty_banks":
        return f"입출금 전체 상대 중 {_BANK[rest]} 계좌", f"{c['counterparty_banks'][rest]:,}개"
    side, _, field = rest.partition(".")
    value = c["counterparties_by_direction"][side][field]
    if field == "count":
        return f"{_FLOW[side]} 상대 계좌", f"{value:,}개"
    return f"{_FLOW[side]} 상대 중 {_BANK[field]} 계좌", f"{value:,}개"


def _format(
    head: str, rest: str, c: dict[str, Any], labels: Labels, exclusive_ok: bool = False
) -> Slot | None:
    names = labels["payment_format"]
    if head == "payment_format_counts":
        row = next(p for p in c["payment_format_counts"] if p["format"] == rest)
        return f"결제 방식 {label_with_code(names[rest], rest)}", f"{row['count']:,}건"
    if head == "payment_formats":
        if not c["payment_formats"]:  # 내부 거래만 — 값 없음(추가 검토 1 M1)
            return None
        return "결제 방식", ", ".join(label_with_code(names[f], f) for f in c["payment_formats"])
    if head == "direction":
        return "거래 방향", direction_label(c, exclusive_ok)
    row = next(u for u in c["unmapped_currencies"] if u["name"] == rest)
    return f"{rest} 통화 거래", f"{row['count']:,}건(대응 미확인)"


def _who(head: str, rest: str, c: dict[str, Any], labels: Labels) -> Slot | None:
    if head == "prior_alert_count":
        return "과거 경보", f"{c['prior_alert_count']:,}건"
    if head == "customer":
        value = c["customer"][rest]
        if rest == "onboarded_at":
            return "고객 등록일", ko_date(date.fromisoformat(str(value)))
        if rest == "country_code":
            return "고객 국가 코드", str(value)
        return _CUSTOMER[rest], labels[rest][value]
    subj = c["subject"]
    if rest == "account_key":
        return "대상 계좌", subj["account_key"]
    etype = labels["entity_type"][subj["entity_type"]] if subj.get("entity_type") else None
    if rest == "entity_type":
        return None if etype is None else ("대상자 유형", etype)
    if subj["entity_name"] is None:
        return None
    name = (
        subj["entity_name"] if rest == "entity_name" or etype is None else f"{subj['entity_name']}({etype})"
    )
    return "보고 대상자", name


def _case(head: str, rest: str, c: dict[str, Any], labels: Labels) -> Slot | None:
    if head == "period":
        start, end = (ko_datetime(datetime.fromisoformat(c["period"][k])) for k in ("start", "end"))
        return "거래 기간", f"{start} ~ {end}"
    if head == "typology":
        return "탐지 유형", label_with_code(labels["typology"][c["typology"]], c["typology"])
    if head == "paths":
        if rest == "kind":
            kind = c["paths"]["kind"]
            return "경로 형태", label_with_code(labels["typology"][kind], kind)
        title, unit = _PATH[rest]
        return title, f"{c['paths'][rest]:,}{unit}"
    if head == "model_signals":
        if not c["model_signals"]:
            return None
        return "모델이 주목한 지표", ", ".join(_obs_name(n, labels) for n in c["model_signals"])
    name, _, part = rest.partition(".")
    o = next(o for o in c["observations"] if o["name"] == name)
    if part == "vs_baseline" and o.get("baseline") is not None:  # 비교는 코드가(원칙 (B))
        cmp = winner(o["value"], o["baseline"], "기준값보다 높음", "기준값보다 낮음", "기준값과 같음")
        value = f"{obs_value(o['value'])} · 평소 기준값 {obs_value(o['baseline'])} · {cmp}"
        return f"{_obs_name(name, labels)} 관측값", value
    if part == "baseline":  # score_reasons 조각에 기준값이 있을 때만 키가 있음(추가 검토 2 M2)
        return (
            None
            if o.get("baseline") is None
            else (f"{_obs_name(name, labels)} 평소 기준값", obs_value(o["baseline"]))
        )
    if part:
        return None
    unit = labels["observation_name_unit"].get(rest, labels["observation_unit"].get(o.get("unit") or "", ""))
    value = f"{obs_value(o['value'])}{unit}"
    if o.get("window_start") and o.get("window_end"):  # 초안 v4 GROUNDS 와 같은 구간 표기
        value += f"({o['window_start']}~{o['window_end']} 기준)"
    return f"{_obs_name(rest, labels)} 관측값", value


def _obs_name(name: str, labels: Labels) -> str:
    """관측 이름 한글 — 표기 사전에 없는 이름은 코드값 그대로(facts 값이라 참, 04)."""
    return labels["observation_name"].get(name, name)


def count_value(key: str, c: dict[str, Any]) -> int | None:
    """방향 건수 키(`<방향>.count`·`counterparties_by_direction.<방향>.count`)의 값, 그 밖은 None."""
    parts = key.split(".")
    if len(parts) == 2 and parts[0] in _FLOW and parts[1] == "count":
        return (c.get(parts[0]) or {}).get("count")
    if len(parts) == 3 and parts[0] == "counterparties_by_direction" and parts[2] == "count":
        return ((c.get(parts[0]) or {}).get(parts[1]) or {}).get("count")
    return None
