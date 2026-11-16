"""텍스트 → 금액+통화 쌍 추출 (SCRUM-58). 통화 매치만 — 숫자 파싱은 `verification_amount_number`.

규칙 정본 docs/str/06 "AMOUNT_MATCH". `verification_amount` 가 Facts 와 비교해 CodeCheck 로 바꾼다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from aml_ai.str.domain.constants_currency import CURRENCY_ALIASES
from aml_ai.str.domain.verification_amount_gap import gap_before
from aml_ai.str.domain.verification_amount_number import AmountPieces, parse_after, parse_before

# 통화 표기 → ISO 코드. 긴 표기 우선 매칭(CAD "캐나다 달러" 가 USD "달러" 보다 먼저).
_ALIAS_PAIRS: list[tuple[str, str]] = sorted(
    ((alias, code) for code, aliases in CURRENCY_ALIASES.items() for alias in aliases),
    key=lambda ab: -len(ab[0]),
)
# 영문자가 들어간 표기 — 뒤·앞에 영문·숫자 이어지면 통화로 안 봄(`USDT`·`EURO`).
_WORD_ALIASES: set[str] = {a for a, _ in _ALIAS_PAIRS if any(c.isascii() and c.isalpha() for c in a)}
# 뒤쪽 금액 허용 표기(영문 전부 + 기호 `$`·`₩`). 한국어 표기는 숫자 뒤 형태만.
# 비ASCII `₩` 가 isascii() 필터에서 빠지지 않도록 명시(Codex adversarial [medium]).
_LEADING_OK: set[str] = {a for a, _ in _ALIAS_PAIRS if a.isascii() or a in {"₩"}}


@dataclass(frozen=True)
class AmountPair:
    """통화 하나와 금액 하나 쌍. value=None → UNPARSED."""

    raw: str
    currency: str
    value: Decimal | None


def find_pairs(text: str) -> list[AmountPair]:
    """통화 표기 각각에 금액 쌍 하나(없을 수도). 안전망은 바로 붙은 금액을 다 짝지은 뒤에 —
    이미 짝지은 숫자는 다시 쓰지 않는다(숫자 하나 = 한 줄, SCRUM-131 추가 검토)."""
    found: list[AmountPair | tuple[int, str]] = []
    used: list[tuple[int, int]] = []
    for start, end, code, alias in _iter_currency_matches(text):
        direct = _pair_for(text, start, end, code, alias)
        if direct is None:
            found.append((start, code))
        else:
            found.append(direct[0])
            used.append(direct[1])
    out: list[AmountPair] = []
    for item in found:
        if isinstance(item, AmountPair):
            out.append(item)
        elif (gap := gap_before(text, item[0], used)) is not None:
            out.append(AmountPair(raw=gap, currency=item[1], value=None))
    return out


def _iter_currency_matches(text: str) -> Iterable[tuple[int, int, str, str]]:
    """긴 표기부터 소비. 영문·숫자 표기는 뒤에 영문·숫자가 이어지면 거부."""
    taken: list[tuple[int, int]] = []
    for alias, code in _ALIAS_PAIRS:
        for idx, end in _find_all(text, alias):
            if _overlaps(taken, idx, end):
                continue
            if alias in _WORD_ALIASES and not _ascii_boundary(text, idx, end):
                continue
            taken.append((idx, end))
            yield idx, end, code, alias


def _find_all(text: str, alias: str) -> Iterable[tuple[int, int]]:
    pos = 0
    while True:
        idx = text.find(alias, pos)
        if idx < 0:
            return
        pos = idx + 1
        yield idx, idx + len(alias)


def _overlaps(spans: list[tuple[int, int]], a: int, b: int) -> bool:
    return any(not (b <= s or e <= a) for s, e in spans)


def _ascii_boundary(text: str, start: int, end: int) -> bool:
    prev = text[start - 1] if start > 0 else ""
    nxt = text[end] if end < len(text) else ""
    return not _is_alnum(prev) and not _is_alnum(nxt)


def _is_alnum(ch: str) -> bool:
    return bool(ch) and ch.isascii() and (ch.isalpha() or ch.isdigit())


def _pair_for(
    text: str, start: int, end: int, code: str, alias: str
) -> tuple[AmountPair, tuple[int, int]] | None:
    """앞쪽(숫자 뒤 통화) 우선, 앞 금액 없으면 뒤쪽 영문 형태(★B). 쌍과 금액 덩이 위치."""
    before = parse_before(text, start)
    if before is not None:
        stop = len(text[:start].rstrip(" "))
        return _as_pair(before, code), (stop - len(before.raw), stop)
    if alias in _LEADING_OK:
        after = parse_after(text, end)
        if after is not None:
            begin = end + len(text[end:]) - len(text[end:].lstrip(" "))
            return _as_pair(after, code), (begin, begin + len(after.raw))
    return None


def _as_pair(parsed: AmountPieces, code: str) -> AmountPair:
    return AmountPair(raw=parsed.raw, currency=code, value=None if parsed.unparsed else parsed.value)


__all__ = ["AmountPair", "find_pairs"]
