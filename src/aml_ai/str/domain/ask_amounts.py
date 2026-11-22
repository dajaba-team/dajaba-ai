"""질문 답변 금액 — 종류·방향·근거 키 대조 (docs/str/06 "질문 답변" 8번, SCRUM-359 유형 4 · 추가 검토 1~3). 순수 함수.

원칙(추가 검토 3): **판정 못 하면 통과 안 시킴** — 금액이 무엇에 대한 값인지 표시가 없거나 애매하면 UNVERIFIED.
금액마다 같은 문장에서 금액 앞 **가장 가까운 종류 표시**로 종류를 정한다:
합계(`합계`·`총`·`모두`·`전체`) · 최대(`최대`·`가장 큰`·`제일 큰`) · 최소(`최소`·`가장 작은`·`제일 작은`) ·
관측값(`관측값`·`지표`) · 개별 대상(`한 상대에게`·`한 건`·`한 번에` …) — 개별 대상·표시 없음은 UNPARSED(facts 에 개별 금액 없음).
더한 표시 둘(검토 3 멈춤 답 (b)): ① 같은 조각에 최대·최소 표시가 둘 다 있고 `모두 X` 면 X 가 최대·최소 값 둘 다와 같고
두 키 다 인용 ② 방향 낱말이 금액을 바로 꾸미면(`입금액은 X`·`입금이 X`·`들어온 돈은 X` …) 그 방향 합계.
조각 = 같은 문장에서 바로 앞 금액 뒤부터 이 금액 앞까지.
방향은 금액 앞 가장 가까운 방향 낱말. 그 종류·방향의 키 중 **답이 인용한 키**와 값이 같아야 match:
합계 → `<방향>.amount.<통화>`(방향 없으면 그 통화가 한 방향에만 있을 때) · 최대·최소 → `amount_range.<통화>.max/min`
(방향을 말했는데 그 통화가 양쪽에 있으면 범위가 섞여 UNPARSED) · 관측값 → 인용한 금액 관측(unit `amount`, 통화 = basis 끝).
금액 줄은 공용 `find_pairs` 와 같은 순서 — 통화 표기 위치를 같은 규칙으로 다시 구해 원문 위치로 잇는다(공용 파일은 그대로).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal

from aml_ai.shared.schemas.str import CheckReason, CodeCheck, CodeCheckName, Facts
from aml_ai.str.domain.ask_amount_scan import located_pairs, segment
from aml_ai.str.domain.constants_ask import (
    ASK_AMOUNT_KIND_WORDS,
    ASK_BOTH_EXTREMES_WORD,
    ASK_CP_IN_WORDS,
    ASK_CP_OUT_WORDS,
    OBS_AMOUNT_UNIT,
)
from aml_ai.str.domain.verification_amount_scan import AmountPair, find_pairs

_FLOW_IN = tuple(w for w in ASK_CP_IN_WORDS if w != "송금인")
_FLOW_OUT = tuple(w for w in ASK_CP_OUT_WORDS if w != "수취인")
# ② 방향 낱말이 금액을 바로 꾸밈 — `입금액은 X`·`입금이 X`·`들어온 돈은 X`·`보낸 돈은 X`
Ctx = tuple[str | None, str | None]
_LIST_ONLY = re.compile(r"[\s,·와과및]*")  # 나열 — 금액 사이에 구분자만
_DIRECT = re.compile(r"(입금액|출금액|입금|출금|들어온 돈|받은 돈|보낸 돈|나간 돈)\s*(?:은|는|이|가)?\s*$")


def exact_amounts(
    facts: Facts, answer: str, cites: Sequence[str], checks: list[CodeCheck]
) -> list[CodeCheck]:
    """AMOUNT_MATCH 줄을 종류·방향·인용 키로 다시 판정. 위치를 못 맞추면 전부 UNPARSED(원칙)."""
    located = located_pairs(answer)
    rows = [c for c in checks if c.check is CodeCheckName.AMOUNT_MATCH]
    same = len(located) == len(rows) and [p for _, p in located] == find_pairs(answer)
    if not same:
        unparsed = (_fail(c, CheckReason.UNPARSED, "금액 위치를 못 맞춤") for c in rows)
        return [next(unparsed) if c.check is CodeCheckName.AMOUNT_MATCH else c for c in checks]
    judged: dict[int, CodeCheck] = {}
    prev: Ctx | None = None  # 앞 금액(글 순서)의 (종류, 방향) — 나열 이어받기
    for i in sorted(
        range(len(located)), key=lambda k: located[k][0]
    ):  # 판정은 글 순서, 줄은 공용 순서 그대로
        pos, pair = located[i]
        before, after_prev = segment(answer, pos, located, pair)
        listed = after_prev and _LIST_ONLY.fullmatch(before) is not None  # 같은 문장 나열만(추가 검토 4 H2)
        judged[i], prev = _judge(facts, cites, rows[i], pair, before, prev if listed else None)
    it = iter(judged[i] for i in range(len(located)))
    return [next(it) if c.check is CodeCheckName.AMOUNT_MATCH else c for c in checks]


def _judge(
    facts: Facts, cites: Sequence[str], row: CodeCheck, pair: AmountPair, before: str, inherit: Ctx | None
) -> tuple[CodeCheck, Ctx | None]:
    """→ (줄, 이 금액의 (종류, 방향)). `inherit` = 구분자만 사이에 둔 앞 금액의 표시(나열 `9800.25 EUR, 42750.50 USD`)."""
    if pair.value is None:
        return row, None  # UNPARSED 그대로
    # ② 방향이 바로 꾸밈 → 합계 — 최대·최소·개별 대상 표시가 같은 조각에 없을 때만(추가 검토 4 H1)
    direct = None if any(_has(before, k) for k in ("max", "min", "single")) else _DIRECT.search(before)
    kind, word = ("total", "") if direct else _nearest(before, ASK_AMOUNT_KIND_WORDS)
    if kind == "total" and word == ASK_BOTH_EXTREMES_WORD and _has(before, "max") and _has(before, "min"):
        side = _nearest(before, {"inbound": _FLOW_IN, "outbound": _FLOW_OUT})[0]
        return _both_extremes(facts, cites, row, pair, side), None
    if kind is None and inherit is not None:
        kind, side = inherit
    else:
        side = (
            _side_of(direct.group(1))
            if direct
            else _nearest(before, {"inbound": _FLOW_IN, "outbound": _FLOW_OUT})[0]
        )
    if kind in (None, "single"):
        return _fail(
            row, CheckReason.UNPARSED, "금액 종류 표시 없음·개별 대상 — facts 에 개별 금액 없음"
        ), None
    expected = _expected(facts, kind, side, pair.currency, cites)
    if expected is None:
        return _fail(row, CheckReason.UNPARSED, f"{kind} 방향을 정할 수 없음"), None
    hit = next((k for k, v in expected.items() if v == pair.value and k in cites), None)
    if hit is not None:
        return row.model_copy(update={"match": True, "reason": None, "source_value": hit}), (kind, side)
    reason = CheckReason.MISSING if pair.value in expected.values() else CheckReason.MISMATCH
    source = " · ".join(f"{k}={v}" for k, v in expected.items()) or "facts 에 그 종류 금액 없음"
    return _fail(row, reason, source), None


def _expected(
    facts: Facts, kind: str, side: str | None, code: str, cites: Sequence[str]
) -> dict[str, Decimal] | None:
    flows = {"inbound": facts.inbound, "outbound": facts.outbound}
    has = {name: [r for r in flow.by_currency if r.currency == code] for name, flow in flows.items()}
    if kind == "total":
        sides = [side] if side else [n for n, rows in has.items() if rows]
        if len(sides) != 1:
            return None
        return {f"{sides[0]}.amount.{code}": Decimal(r.total) for r in has[sides[0]]}
    if kind in ("max", "min"):
        if side and has["outbound" if side == "inbound" else "inbound"]:
            return None  # 범위가 두 방향 섞임
        rng = [r for r in facts.amount_range if r.currency == code]
        return {f"amount_range.{code}.{kind}": Decimal(getattr(r, kind)) for r in rng}
    return {  # observation
        f"observations.{o.name}": Decimal(str(o.value))
        for o in facts.observations
        if f"observations.{o.name}" in cites
        and _obs_currency(o.unit, o.basis) == code
        and o.value is not None
    }


def _both_extremes(
    facts: Facts, cites: Sequence[str], row: CodeCheck, pair: AmountPair, side: str | None
) -> CodeCheck:
    """`최대와 최소는 모두 X` — X 가 max·min 둘 다와 같고 두 키 다 인용됐을 때만(검토 3 멈춤 답 ①).
    방향을 말했으면 그 방향에 그 통화 거래가 있고 반대 방향엔 없어야(범위가 그 방향 것) — 추가 검토 4 H1."""
    code = pair.currency
    if side is not None:
        flows = {"inbound": facts.inbound, "outbound": facts.outbound}
        other = "outbound" if side == "inbound" else "inbound"
        mine = any(r.currency == code for r in flows[side].by_currency)
        if not mine or any(r.currency == code for r in flows[other].by_currency):
            return _fail(row, CheckReason.UNPARSED, f"{side} 쪽 {code} 범위를 정할 수 없음")
    keys = {
        f"amount_range.{code}.{end}": Decimal(getattr(r, end))
        for r in facts.amount_range
        if r.currency == code
        for end in ("max", "min")
    }
    if len(keys) == 2 and all(v == pair.value and k in cites for k, v in keys.items()):
        return row.model_copy(update={"match": True, "reason": None, "source_value": " · ".join(keys)})
    return _fail(
        row,
        CheckReason.MISMATCH,
        " · ".join(f"{k}={v}" for k, v in keys.items()) or "facts 에 그 통화 범위 없음",
    )


def _has(before: str, kind: str) -> bool:
    return any(w in before for w in ASK_AMOUNT_KIND_WORDS[kind])


def _side_of(word: str) -> str:
    return "inbound" if any(w in word for w in _FLOW_IN) else "outbound"


def _nearest(before: str, groups: dict[str, tuple[str, ...]]) -> tuple[str | None, str]:
    """금액 앞에서 가장 가까운(마지막에 나온) 낱말의 (묶음 이름, 낱말)."""
    best: tuple[int, str, str] | None = None
    for name, words in groups.items():
        for w in words:
            i = before.rfind(w)
            if i >= 0 and (best is None or i + len(w) > best[0]):
                best = (i + len(w), name, w)
    return (best[1], best[2]) if best else (None, "")


def _obs_currency(unit: str | None, basis: str | None) -> str | None:
    if unit != OBS_AMOUNT_UNIT or not basis:
        return None
    return basis.rsplit("_", 1)[-1].upper()


def _fail(row: CodeCheck, reason: CheckReason, source: str) -> CodeCheck:
    return row.model_copy(update={"match": False, "reason": reason, "source_value": source})
