"""슬롯 문장 표기 도우미 — 쉼표·날짜 모양·조사만 (docs/str/05 narrative_v4 "슬롯 생성기"). 순수.

새 숫자를 만들지 않는다: 합산·환산·반올림 없음. 금액은 facts 문자열의 정수부에 쉼표만 넣는다.
"""

from __future__ import annotations

from datetime import date, datetime

_HANGUL_FIRST = 0xAC00
_HANGUL_LAST = 0xD7A3
_JONG_COUNT = 28
_JONG_RIEUL = 8
# 숫자를 한국어로 읽을 때 받침 여부(0 영·1 일·3 삼·6 육·7 칠·8 팔 = 받침, 2 이·4 사·5 오·9 구 = 없음)
_DIGIT_HAS_BATCHIM = {"0": True, "1": True, "3": True, "6": True, "7": True, "8": True}
_DIGIT_RIEUL = {"1", "7", "8"}


def _last_sound(word: str) -> tuple[bool, bool]:
    """(받침 있음, 받침이 ㄹ). 한글·숫자 밖이면 받침 없음으로 본다."""
    ch = word.rstrip()[-1:] if word.strip() else ""
    if ch and _HANGUL_FIRST <= ord(ch) <= _HANGUL_LAST:
        jong = (ord(ch) - _HANGUL_FIRST) % _JONG_COUNT
        return jong != 0, jong == _JONG_RIEUL
    if ch.isdigit():
        return _DIGIT_HAS_BATCHIM.get(ch, False), ch in _DIGIT_RIEUL
    return False, False


def topic(word: str) -> str:
    """은/는."""
    return word + ("은" if _last_sound(word)[0] else "는")


def topic_before_paren(word: str) -> str:
    """은/는 — 괄호로 끝나면 괄호 앞 말 기준(`비중(거래 수 가중 평균)은`). 관측 항목 표기용(SCRUM-264)."""
    base = word[: word.rfind("(")] if word.endswith(")") and "(" in word else word
    return word + topic(base)[len(base) :]


def with_ro(word: str) -> str:
    """으로/로 — ㄹ 받침은 로."""
    has, rieul = _last_sound(word)
    return word + ("으로" if has and not rieul else "로")


def with_imyeo(word: str) -> str:
    """`이며` — 받침과 상관없이(`투자이며`, 05)."""
    return f"{word}이며"


def with_imeuro(word: str) -> str:
    """`이므로` — 받침과 상관없이(`투자이므로`, 05)."""
    return f"{word}이므로"


def copula(word: str) -> str:
    """서술 끝 `임`."""
    return f"{word}임"


def money(amount: str) -> str:
    """facts 금액 문자열 → 정수부 쉼표만. `42750.50` → `42,750.50`."""
    whole, dot, frac = amount.partition(".")
    return f"{int(whole):,}{dot}{frac}"


def ko_date(d: date) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일"


def ko_datetime(ts: datetime) -> str:
    """`2022년 9월 2일 00:14` — 초가 0이 아니면 `00:14:30`."""
    clock = f"{ts.hour:02d}:{ts.minute:02d}" + (f":{ts.second:02d}" if ts.second else "")
    return f"{ko_date(ts)} {clock}"


def obs_value(value: float) -> str:
    """정수 값이면 `3`, 아니면 원값 그대로(반올림 금지)."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def label_with_code(label: str, code: str) -> str:
    """`한글(코드)` — 표기가 원문과 같으면 괄호 병기 생략(`ACH(ACH)` 안 씀)."""
    return label if label == code else f"{label}({code})"
