"""SCRUM-225 — 규칙 12 facts 필수 항목 커버리지 (docs/str/10 「RAG 켬/끔 2차」, 05 narrative_v3).

`fact_coverage(narrative, facts)` — 필수 항목 중 본문에 나온 수. 순수 함수, LLM 0.
- 찾는 범위: observations 값·관측 구간은 **GROUNDS 본문만**(DATE 의 거래 날짜·다른 섹션 건수가 가리지 않게,
  추가 검토 1차), 나머지 항목은 7섹션 전체
- 코드는 원문 일치(`SALES_DEPOSIT`), 숫자는 쉼표 무시(`42,750.50` = `42750.50`)
- 건수는 방향 낱말 뒤 20자 안의 첫 `{n}건`("출금 거래는 0건이며"·"내부거래는 0건"), 또는 거꾸로 `{n}건` 바로 뒤
  3자 안에서 시작하는 방향 낱말("3건이 입금"·"0건 출금"). "0건이며 입금" 처럼 그보다 멀면 안 셈(섞임 방지)
- 관측 구간은 window_start·window_end 의 날짜 둘 다
- null·빈 항목은 분모에서 뺌. **한계**: 코드를 한국어로만 옮겨 쓴 경우("매출대금 입금")는 못 셈(09)

사후 기준선 (v2 끔 소급, 블라인드 md + 키):
    uv run --frozen --extra dev python -m tests.str.rag_onoff_coverage <blind.md> <key.json> [out.json]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain.constants import CURRENCY_CODES

_NEAR = r"(?:(?!\d\s*건)[^.\n]){0,20}?"  # 다른 "{n}건" 을 건너뛰지 않음


def _code(v: str) -> str:
    return rf"(?<![A-Za-z_]){re.escape(v)}(?![A-Za-z_])"


def _num(v: str) -> str:
    return rf"(?<![\d.]){re.escape(v)}(?!\d)"


def _count(words: str, n: int) -> str:
    forward = rf"(?:{words}){_NEAR}(?<![\d,.]){n}\s*건"
    backward = rf"(?<![\d,.]){n}\s*건[^\d.\n]{{0,2}}(?:{words})"  # 방향 낱말이 "건" 뒤 3자 안에서 시작
    return f"{forward}|{backward}"


def _value(x: float) -> str:
    return rf"(?<![\d.]){int(x)}(?:\.0+)?(?![\d.])" if float(x).is_integer() else _num(str(x))


def _currency(code: str) -> str:
    names = [code] + [name for name, iso in CURRENCY_CODES.items() if iso == code]
    return "|".join(re.escape(n) for n in names)


def _subject_items(facts: Facts) -> list[tuple[str, str]]:
    c = facts.customer
    items = [] if c is None else [
        (f"customer.{k}", _code(v))
        for k in ("account_purpose", "industry", "risk_level")
        if (v := getattr(c, k))
    ]  # fmt: skip
    return items + [("prior_alert_count", _count("경보", facts.prior_alert_count))]


def _flow_items(facts: Facts) -> list[tuple[str, str]]:
    items = [
        (f"payment_format_counts.{p.format}", rf"{re.escape(p.format)}{_NEAR}(?<![\d,.]){p.count}\s*건")
        for p in facts.payment_format_counts
    ]
    flows = (("inbound", facts.inbound), ("outbound", facts.outbound))
    currencies = sorted({c.currency for _, f in flows for c in f.by_currency})
    items += [(f"currency.{cur}", _currency(cur)) for cur in currencies]
    items += [(f"unmapped_currencies.{u.name}", re.escape(u.name)) for u in facts.unmapped_currencies]
    items += [
        ("inbound.count", _count("입금|유입", facts.inbound.count)),
        ("outbound.count", _count("출금|송금", facts.outbound.count)),
    ]
    items += [(f"{side}.amount.{c.currency}", _num(c.total)) for side, f in flows for c in f.by_currency]
    for a in facts.amount_range:
        items += [
            (f"amount_range.{a.currency}.min", _num(a.min)),
            (f"amount_range.{a.currency}.max", _num(a.max)),
        ]
    return items + [("internal.count", _count(r"내부\s*거래", facts.internal.count))]


def _grounds_items(facts: Facts) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for o in facts.observations:
        items.append((f"observations.{o.name}", _value(o.value)))
        if o.window_start and o.window_end:
            d1, d2 = (re.escape(w.date().isoformat()) for w in (o.window_start, o.window_end))
            items.append((f"observations.{o.name}.window", rf"(?=[\s\S]*{d1})(?=[\s\S]*{d2})"))
    return items


def _joined(sections: list[Any]) -> str:
    return re.sub(r"(?<=\d),(?=\d{3})", "", "\n".join(s.text for s in sections))


def fact_coverage(narrative: list[Any], facts: Facts) -> dict[str, Any]:
    """`{"covered": n, "required": m, "missing": [항목…]}` — 항목 이름은 fact 키 꼴."""
    text = _joined(narrative)
    grounds = _joined([s for s in narrative if s.section.value == "GROUNDS"])
    items = [(k, p, text) for k, p in _subject_items(facts) + _flow_items(facts)]
    items += [(k, p, grounds) for k, p in _grounds_items(facts)]
    missing = [key for key, pat, scope in items if not re.search(pat, scope)]
    return {"covered": len(items) - len(missing), "required": len(items), "missing": missing}


def baseline(md: str, key: dict[str, dict[str, bool]]) -> dict[str, Any]:
    """블라인드 md + 키 → 사건별 ON/OFF 커버리지와 합계 (5건 합산 covered ÷ required)."""
    from tests.str.rag_onoff_unsupported_post import _load_facts, _parse_blind

    cases: dict[str, Any] = {}
    total = {"on": [0, 0], "off": [0, 0]}
    for case_id, sides in _parse_blind(md).items():
        facts = _load_facts(case_id)
        for side, sections in sides.items():
            label = "on" if key[case_id][f"{side}_rag"] else "off"
            cov = fact_coverage(sections, facts)
            cases.setdefault(case_id, {})[label] = cov
            total[label][0] += cov["covered"]
            total[label][1] += cov["required"]
    return {"cases": cases, "total": {k: {"covered": c, "required": r} for k, (c, r) in total.items()}}


def main() -> int:
    md, key = Path(sys.argv[1]).read_text(encoding="utf-8"), json.loads(Path(sys.argv[2]).read_text())
    out = json.dumps(baseline(md, key), ensure_ascii=False, indent=2)
    print(out)
    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_text(out + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
