"""요약 v2 전용 금액 표기 대조 — 허용 문자열 대조 (SCRUM-340 추가 검토 1~3, docs/str/06 "요약 v2 금액 표기"). 순수.

공용 AMOUNT_MATCH(`verification_amount*`)는 그대로 돌고, 이 검사가 같은 이름 `AMOUNT_MATCH` 줄을 더한다.
v2 는 LLM 에 준 금액 문자열을 "글자 그대로" 옮겨 쓰므로 모델이 쓴 금액을 해석하지 않고 뒤집어 본다(검토 3). 줄마다:
① 허용 문자열(입금·출금 합계, amount_range min·max 의 완성 표기 `62,992,819.38 유로(EUR)`)이 글자 그대로 나온 곳을 찾음
② 한 줄에 둘 이상이면 전부 MISMATCH(한 줄에 금액 하나) · 바로 앞(공백 넘어)이 부호·범위 기호면 MISMATCH
③ 찾은 것을 지운 나머지에 금액 모양(숫자 + 통화 표현 — 영문 대문자 3자·통화 이름·`(코드)`)이 남으면 MISMATCH
   (틀린 금액·미등록 코드·틀린 괄호 코드·완성 표기가 아닌 금액 모두 여기로)
금액 모양이 아닌 것(예외 둘): 날짜에 이어진 숫자(`2022-09-02`) · 영문·`#`·`*`·`_` 에 붙은 식별자 숫자. 건수(`3건`)·
관측값 소수(`0.85`)는 통화 표현이 없어 원래 금액 모양이 아님.
방향(입금↔출금)·종류(합계↔최소↔최대)를 줄 나눠 바꿔 쓴 문장은 못 잡음(알려진 한계, 08·09).
"""

from __future__ import annotations

import re

from aml_ai.shared.schemas.str import CheckReason, CodeCheck, CodeCheckName, Facts
from aml_ai.str.domain.constants_currency import CURRENCY_ALIASES
from aml_ai.str.domain.display_labels_check import Labels
from aml_ai.str.domain.summary_amounts import display_amount

_CODES = tuple(CURRENCY_ALIASES)
_NAMES = "|".join(
    re.escape(a)
    for a in sorted(
        {a for v in CURRENCY_ALIASES.values() for a in v if a not in _CODES}, key=len, reverse=True
    )
)
_BEFORE = "-−+~～–"  # 허용 문자열 바로 앞이면 실패(부호·범위 기호)
_NOT_AFTER = r"(?<![\d.,#_*A-Za-z])(?<!\d[-/])"  # 예외 둘 — 식별자·날짜에 붙은 숫자는 금액 아님
_AMOUNT_SHAPE = re.compile(
    rf"{_NOT_AFTER}(?P<sign>[{_BEFORE}][ \t]*)?(?<![\d.,])(?P<num>\d{{1,3}}(?:,\d{{3}})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d,])"
    rf"[ \t]*(?:[A-Z]{{3}}(?![A-Za-z])|(?:{_NAMES})|\([ \t]*[A-Za-z]{{2,4}}[ \t]*\))"
)
_HOLE = "\x00"  # 지운 자리 — 앞뒤 글자가 이어 붙지 않게
_ONE_PER_LINE = "한 줄에 금액 {n}개 — summary_v2 는 한 줄에 하나"


def summary_amount_checks(facts: Facts, lines: list[str], labels: Labels) -> list[CodeCheck]:
    """`labels` = LLM 입력을 만든 것과 같은 표기 사전 — 허용 문자열이 LLM 에 준 글자와 같아짐."""
    allowed_map = allowed_strings(facts, labels)
    out: list[CodeCheck] = []
    for line in lines:
        hits = _hits(line, allowed_map)
        for start, end, source in hits:
            prefix = line[:start].rstrip(" \t")
            if len(hits) > 1:
                out.append(_row(line[start:end], _ONE_PER_LINE.format(n=len(hits)), False))
            elif prefix[-1:] and prefix[-1] in _BEFORE:
                out.append(_row(line[len(prefix) - 1 : end], f"부호·범위 기호 붙은 금액 — {source}", False))
            else:
                out.append(_row(line[start:end], source, True))
        rest = _blank(line, hits)
        allowed = " · ".join(allowed_map.values()) or "facts 금액 없음"
        out += [
            _row(m.group(0).strip(), f"허용 표기 아님 — {allowed}", False)
            for m in _AMOUNT_SHAPE.finditer(rest)
        ]
    return out


def allowed_strings(facts: Facts, labels: Labels) -> dict[str, str]:
    """{완성 표기: 출처 표시} — 입금·출금 합계 + amount_range min·max(`display_amount` — LLM 입력과 같은 함수)."""
    out: dict[str, str] = {}
    for name, rows in (("inbound", facts.inbound.by_currency), ("outbound", facts.outbound.by_currency)):
        for r in rows:
            shown = display_amount(r.total, r.currency, labels)
            out.setdefault(shown, f"{name}.amount.{r.currency}={shown}")
    for r in facts.amount_range:
        for end, value in (("min", r.min), ("max", r.max)):
            shown = display_amount(value, r.currency, labels)
            out.setdefault(shown, f"amount_range.{r.currency}.{end}={shown}")
    return out


def _hits(line: str, allowed: dict[str, str]) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for shown in sorted(allowed, key=len, reverse=True):
        for m in re.finditer(rf"(?<![\d.,]){re.escape(shown)}", line):
            if not any(s < m.end() and m.start() < e for s, e, _ in found):
                found.append((m.start(), m.end(), allowed[shown]))
    return sorted(found)


def _blank(line: str, hits: list[tuple[int, int, str]]) -> str:
    for start, end, _ in sorted(hits, reverse=True):
        line = line[:start] + _HOLE + line[end:]
    return line


def _row(draft: str, source: str, matched: bool) -> CodeCheck:
    return CodeCheck(
        check=CodeCheckName.AMOUNT_MATCH,
        section=None,
        draft_value=draft.replace(_HOLE, " "),
        source_value=source,
        match=matched,
        reason=None if matched else CheckReason.MISMATCH,
    )
