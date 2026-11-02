"""금액 모양 판정 보조 — 근사·수사·금액 모양 제외·단위 합산 (SCRUM-58).

`verification_amount_number` 가 import 하는 보조. 숫자 자체 파싱이 아니라 **분위기 판정** 쪽만.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aml_ai.str.domain.constants import (
    APPROXIMATE_WORDS,
    KOREAN_NUMERAL_BIG,
    KOREAN_NUMERAL_SMALL,
    KOREAN_UNIT_MULTIPLIER,
    NON_AMOUNT_TRAILERS,
)


def combine(chunks: list[tuple[Decimal, str | None]]) -> Decimal | None:
    """덩이를 큰 단위부터 내려가며 합산. 역전·중복이면 None."""
    units = KOREAN_UNIT_MULTIPLIER
    ordered: list[tuple[Decimal, Decimal]] = []
    seen: set[str] = set()
    for dec, unit in chunks:
        if unit is None:
            ordered.append((dec, Decimal(1)))
            continue
        if unit in seen:
            return None
        seen.add(unit)
        ordered.append((dec, units[unit]))
    if not ordered:
        return None
    mults = [m for _, m in ordered]
    desc = sorted(mults, reverse=True)
    if mults != desc and list(reversed(mults)) != desc:
        return None
    return sum((dec * mult for dec, mult in ordered), Decimal(0))


def to_decimal(num_text: str) -> Decimal:
    try:
        return Decimal(num_text.replace(",", ""))
    except InvalidOperation:
        return Decimal(0)


def approx_before(text: str, start: int) -> bool:
    look = text[:start].rstrip()
    return any(look.endswith(w) for w in APPROXIMATE_WORDS)


def approx_after(text: str, end: int) -> bool:
    look = text[end:].lstrip()
    return any(look.startswith(w) for w in APPROXIMATE_WORDS)


def non_amount_trailer_after(text: str, end: int) -> bool:
    """숫자 바로 뒤에 `건·회·…` 또는 `-·/ 날짜 모양`이면 금액 아님(건수·날짜 — 다른 check 몫)."""
    tail = text[end:]
    stripped = tail.lstrip(" ")
    if len(tail) != len(stripped):
        return False
    if any(stripped.startswith(t) for t in NON_AMOUNT_TRAILERS):
        return True
    return bool(stripped[:1] in {"-", "/"} and stripped[1:2].isdigit())


def trailing_korean_numeral(text: str) -> str:
    """끝에서 한글 수사 글자를 모은 조각. 공백 허용."""
    out: list[str] = []
    i = len(text) - 1
    while i >= 0:
        ch = text[i]
        if ch == " ":
            i -= 1
            continue
        if _is_numeral_char(ch):
            out.append(ch)
            i -= 1
            continue
        break
    return "".join(reversed(out))


def leading_korean_numeral(text: str) -> str:
    """앞에서 한글 수사 글자를 모은 조각. 수사 글자 사이 공백만 허용(수사 시작 전 공백은 호출자 strip)."""
    out: list[str] = []
    for ch in text:
        if ch == " ":
            if out:
                continue
            break
        if _is_numeral_char(ch):
            out.append(ch)
            continue
        break
    return "".join(out)


def is_numeral_amount(s: str) -> bool:
    """수사 글자 2자 이상이고 억·천만·만·천·백·십 중 하나 포함(★A 3·★B)."""
    core = s.replace(" ", "")
    if len(core) < 2:
        return False
    big = KOREAN_NUMERAL_BIG | {"십"}
    return any(c in big for c in core)


def token_boundary_broken(text: str, pos: int, side: str) -> bool:
    """숫자 토큰 매치 바깥 글자가 토큰을 깨는가 (Codex adversarial [high] #1).

    side='before': `text[pos-1]` 가 `-`·`+`·`,`·숫자 → 토큰 앞 깨짐
      예 `-42,750.50`·`1,42,750.50`·`9142,750.50` — 매치는 `42,750.50` 뿐이지만 앞에 조각 남음.
    side='after':  `text[pos]` 뒤가 `,숫자`·`.숫자` → 토큰 뒤 깨짐
      예 `42,750.50,000`·`42.5.0` — 매치는 `42,750.50` 또는 `42.5` 뒤에 더 붙음.
    """
    if side == "before":
        if pos <= 0:
            return False
        prev = text[pos - 1]
        return prev in "-+," or prev.isdigit()
    if pos >= len(text):
        return False
    nxt = text[pos]
    nnxt = text[pos + 1 : pos + 2]
    return nxt in ".," and nnxt.isdigit()


def classify_adjacent(text: str, pos: int, side: str) -> str | None:
    """통화 표기 바로 바깥 글자가 **근사 수식어** 또는 **수사 금액 모양**이면 매치된 raw.

    아라비아 숫자가 안 붙어 있어도 UNPARSED 로 떨어뜨려야 할 때 호출. 통화 위치만 바꿔 UNPARSED 를
    우회하지 못하도록 앞·뒤 둘 다 같은 함수(Codex adversarial [high] #2).

    side='before': `text[:pos].rstrip()` 끝에서 approx 수식어 또는 수사 꼬리 추출.
    side='after':  `text[pos:].lstrip()` 앞에서 approx 수식어 또는 수사 머리 추출.
    """
    if side == "before":
        look = text[:pos].rstrip()
        for w in APPROXIMATE_WORDS:
            if look.endswith(w):
                return w
        syl = trailing_korean_numeral(look)
        return syl if syl and is_numeral_amount(syl) else None
    look = text[pos:].lstrip()
    for w in APPROXIMATE_WORDS:
        if look.startswith(w):
            return w
    syl = leading_korean_numeral(look)
    return syl if syl and is_numeral_amount(syl) else None


def _is_numeral_char(ch: str) -> bool:
    return ch in KOREAN_NUMERAL_SMALL or ch in KOREAN_NUMERAL_BIG or ch == "십"
