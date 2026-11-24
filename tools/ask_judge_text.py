"""질문 답변 판정용 글·자리표 방향 대조 (SCRUM-362 ★B3-5 · 추가 검토 1 H4 · 2 M1, docs/str/08). 판정 도구 전용.

원칙(진희): "맞는지는 읽는 사람이 보는 글, 틀렸는지는 LLM 이 쓴 글로." 이름표는 코드가 붙인 참인 사실이라 맞음의 근거는
되지만 LLM 주장이 아니라 틀림의 근거는 안 된다. **서비스 검사(`ask_checks`·`ask_slots`)와 코드를 나누지 않는다** —
자리표 읽기·조사·방향 낱말·절 나누기를 여기서 따로 둔다(값 표기만 이름표 표 `slot` 을 씀). 자리표 없는 답(v1·v2)은 그대로.
"""

from __future__ import annotations

import re

from aml_ai.str.domain.ask_bundles import AskPiece
from aml_ai.str.domain.ask_slot_labels import slot
from aml_ai.str.domain.constants_ask import ASK_SENTENCE_STOPS
from aml_ai.str.domain.display_labels_check import Labels

_SLOT = re.compile(r"\{\{([^{}|]*)(?:\|([^{}]*))?\}\}")
# 판정용 방향 낱말(서비스 목록과 따로) — 양방향 낱말은 먼저 지움
_IN = ("입금", "들어온", "들어오", "받은", "받았", "송금인", "유입")
_OUT = ("출금", "보낸", "보냈", "나간", "나가", "수취인", "유출")
_BOTH = ("입출금", "입·출금", "입금과 출금", "입금·출금", "입금 및 출금", "양방향")
# 절 끊기: 문장 끝 · `…고,`·`…며,` 뒤 · `…지만`·`…는데` 뒤 · `대신`·`반면`·`그리고` 앞(추가 검토 2 M1)
_CLAUSE = re.compile(
    rf"[{re.escape(ASK_SENTENCE_STOPS)}\n]|(?<=고|며),|(?<=지만)|(?<=는데)|(?=대신|반면|그리고)"
)
_BOTH_KEYS = ("payment_format_counts.", "counterparty_banks.", "amount_range.")
_BOTH_EXACT = ("payment_formats", "counterparties.count")


def judge_text(raw: str, piece: AskPiece, labels: Labels) -> str:
    """틀림 규칙에 쓰는 글 — `{{키|조사}}` → 값 + 조사(그대로 붙임), 절 전환은 마침표로(정규식 `[^.]*?` 가 절을 못 넘게)."""

    def one(m: re.Match[str]) -> str:
        key = m.group(1)
        pair = _slot(key, piece, labels)
        return "" if pair is None else pair[1] + (m.group(2) or "")

    return _CLAUSE.sub(lambda m: m.group(0) if m.group(0) in ".!?\n" else ". ", _SLOT.sub(one, raw))


def slot_direction_conflicts(raw: str, piece: AskPiece) -> int:
    """자리표와 **같은 절**(앞·뒤 LLM 글)의 방향 낱말이 그 키의 방향과 어긋난 수(방향 없는 키 + 방향 낱말도 어긋남)."""
    return sum(v == "wrong" for v in _slot_links(raw, piece))


def slot_direction_unclear(raw: str, piece: AskPiece) -> bool:
    """한 절에 입금·출금 낱말이 섞여 자리표와의 연결을 못 정함 → 판정 보류."""
    return any(v == "unclear" for v in _slot_links(raw, piece))


def _slot_links(raw: str, piece: AskPiece) -> list[str]:
    blank = _blank(raw)
    bounds = sorted({0, len(blank), *(m.start() for m in _CLAUSE.finditer(blank))})
    found = []  # (절 시작, 자리표 방향)
    for m in _SLOT.finditer(raw):
        side = _key_side(m.group(1)) if m.group(1) in piece.keys else None
        if side is not None:
            found.append((max(b for b in bounds if b <= m.start()), side))
    out = []
    for start, side in found:
        end = min(b for b in bounds if b > start)
        said = _sides(blank[start:end])
        siblings = {s for st, s in found if st == start}
        if len(said) > 1:
            out.append("unclear")
        elif said and said != {side} and not said <= siblings:  # 같은 절 다른 자리표의 방향이면 그쪽 낱말
            out.append("wrong")
    return out


def _blank(raw: str) -> str:
    """자리표를 같은 길이 공백으로 — 조사는 남김(`{{…|이며}},` 뒤 쉼표가 `_CLAUSE` 경계가 되게, ★B8)."""
    return _SLOT.sub(lambda m: " " * (len(m.group(0)) - len(m.group(2) or "")) + (m.group(2) or ""), raw)


def _sides(text: str) -> set[str]:
    for word in _BOTH:
        text = text.replace(word, " ")
    return {s for s, words in (("in", _IN), ("out", _OUT)) if any(w in text for w in words)}


def _key_side(key: str) -> str | None:
    if key.startswith(("inbound.", "counterparties_by_direction.inbound.")):
        return "in"
    if key.startswith(("outbound.", "counterparties_by_direction.outbound.")):
        return "out"
    if key.startswith(_BOTH_KEYS) or key in _BOTH_EXACT:
        return "both"
    return None


# 비교 꼴(판정 도구 따로 — 서비스 `RE_OUTSIDE_COMPARE` 와 공유 안 함): 자리표 A (조사) 자리표 B 보다 (더) 많/적/높/낮/크/작
_PAIR = re.compile(
    r"\{\{([^{}|]*)(?:\|[^{}]*)?\}\}\s*[이가은는]?\s*\{\{([^{}|]*)(?:\|[^{}]*)?\}\}\s*보다\s*(?:더\s*)?(많|적|높|낮|크|커|작)"
)
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def comparison_wrong(raw: str, piece: AskPiece) -> bool:
    """LLM 이 두 자리표 값을 직접 비교한 꼴의 대소가 값과 어긋나거나, compare 자리표가 facts 로 따로 계산한 것과
    어긋나면(절의 지표 낱말 · 통화 · 두 값 · 승자 — 추가 검토 3 H6) True. 값을 못 읽으면 False — 다른 규칙 몫."""
    from aml_ai.str.infrastructure.display_labels import load_display_labels

    labels = load_display_labels()
    if _compare_slot_wrong(raw, piece, labels):
        return True
    for m in _PAIR.finditer(raw):
        a, b = (_value(k, piece, labels) for k in (m.group(1), m.group(2)))
        if a is None or b is None:
            continue
        says_more = m.group(3) in ("많", "높", "크", "커")
        if (a > b) != says_more or a == b:
            return True
    return False


def _value(key: str, piece: AskPiece, labels: Labels) -> float | None:
    pair = _slot(key, piece, labels)
    found = _NUM.search(pair[1]) if pair else None
    return float(found.group(0).replace(",", "")) if found else None


def _slot(key: str, piece: AskPiece, labels: Labels) -> tuple[str, str] | None:
    """값 표기만 이름표 표를 씀 — 범위·내부 거래 정보도 서비스 렌더링과 같은 입력으로."""
    if key not in piece.keys:
        return None
    whole = piece.scope is not None and piece.scope.whole_alert
    return slot(
        key,
        piece.content,
        labels,
        exclusive_ok=whole and piece.scope is not None and piece.scope.ownership_known,
        non_external=piece.non_external,
        evidence_scoped=not whole,
    )


# compare 자리표 — 판정 도구가 facts 조각에서 따로 계산(서비스 `ask_slot_compare` 와 공유 안 함, 추가 검토 3 H6)
_AMOUNT_WORDS = ("금액", "합계", "얼마", "돈")
_SCOPE_MARK = re.compile(
    r" \((?:근거 거래|대외 거래)(?: · 대외 거래)? 기준\)$"
)  # 범위 표시는 값 비교에서 뺌(04 ★B8)
_COUNT_WORDS = ("건수", "몇 건", "횟수")


def _compare_slot_wrong(raw: str, piece: AskPiece, labels: Labels) -> bool:
    blank = _blank(raw)
    bounds = sorted({0, len(blank), *(m.start() for m in _CLAUSE.finditer(blank))})
    for m in _SLOT.finditer(raw):
        key = m.group(1)
        if not key.startswith("compare.") or key not in piece.keys:
            continue
        start = max(b for b in bounds if b <= m.start())
        said = blank[start : min(b for b in bounds if b > m.start())]
        metric = "count" if key == "compare.count" else "amount"
        if metric == "count" and any(w in said for w in _AMOUNT_WORDS):
            return True
        if metric == "amount" and any(w in said for w in _COUNT_WORDS):
            return True
        pair = _slot(key, piece, labels)
        if pair is None or _SCOPE_MARK.sub("", pair[1]) != _expected_compare(key, piece.content):
            return True
    return False


def _expected_compare(key: str, c: dict) -> str | None:
    """compare 값 글 — 두 값과 승자를 facts 조각에서 따로 셈. 못 세면 None(= 어긋남)."""
    from decimal import Decimal

    ins, outs = c.get("inbound") or {}, c.get("outbound") or {}
    if key == "compare.count":
        a, b = ins.get("count"), outs.get("count")
        if a is None or b is None:
            return None
        return f"입금 {a:,}건, 출금 {b:,}건 · {_who(a, b)}"
    cur = key.removeprefix("compare.amount.")
    tot = [
        next((r["total"] for r in side.get("by_currency", []) if r["currency"] == cur), None)
        for side in (ins, outs)
    ]
    if None in tot:
        return None
    a, b = (Decimal(t) for t in tot)
    return f"입금 {a:,.2f} {cur}, 출금 {b:,.2f} {cur} · {_who(a, b)}"


def _who(a: object, b: object) -> str:
    return "입금이 더 많음" if a > b else "출금이 더 많음" if a < b else "같음"  # type: ignore[operator]
