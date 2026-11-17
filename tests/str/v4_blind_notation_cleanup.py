"""v2 표기 통일 흔적 정리 — 09 2026-11-17 "SCRUM-265 1/2 표기 정리". 숫자·뜻 그대로, 표기만.

- 한글 낱말에 붙은 괄호 속 코드: 유형·통화(`집중 입금(FAN_IN)`)는 코드 그대로. 그 밖은 앞말이 그 코드와 같은 뜻으로
  확인된 말(사전 표기 또는 별칭 표)일 때만 괄호째 지움(`소매업(RETAIL)` → `소매업`), 아니면 표기를 괄호에 남김
  (`계좌목적(SALES_DEPOSIT)` → `계좌목적(매출 대금 수납)`) — 확인 안 된 앞말에서 지우면 값이 사라짐
- 바꾼 표기 바로 뒤 조사를 표기 끝 받침에 맞춤(`값는` → `값은`)
- 같은 말 괄호(`소매업(소매업)`)·겹친 말(`자료는 자료 없음`) 하나로
"""

from __future__ import annotations

import re

HANGUL_FIRST, HANGUL_LAST, JONG_COUNT, RIEUL = 0xAC00, 0xD7A3, 28, 8
# (받침 있음, 받침 없음) — 로/으로 는 ㄹ 받침이면 로
PARTICLE_PAIRS = (("은", "는"), ("이", "가"), ("을", "를"), ("과", "와"), ("으로", "로"))
# 사전 표기 말고 같은 뜻으로 확인된 앞말 — 228 공개 md 원문에서 나온 것만(테스트로 고정)
PAREN_ALIASES: dict[str, tuple[str, ...]] = {"SALES_DEPOSIT": ("매출대금 입금", "매출 대금 입금")}
REPEATED_ABSENCE = re.compile(r"(?<![가-힣])([가-힣]+)(은|는|이|가) \1 없음")


def _is_hangul(ch: str) -> bool:
    return HANGUL_FIRST <= ord(ch) <= HANGUL_LAST


def _jong(ch: str) -> int:
    return (ord(ch) - HANGUL_FIRST) % JONG_COUNT


def _hangul_run(text: str, start: int, step: int) -> str:
    """start 에서 step 방향으로 이어진 한글 글자(왼쪽이면 원래 순서로 돌려줌)."""
    chars = []
    i = start
    while 0 <= i < len(text) and _is_hangul(text[i]):
        chars.append(text[i])
        i += step
    return "".join(chars if step > 0 else reversed(chars))


def attached_paren(text: str, start: int, end: int) -> str | None:
    """코드가 한글 낱말에 바로 붙은 괄호 속이면 그 낱말, 아니면 None."""
    if start < 2 or end >= len(text) or text[start - 1] != "(" or text[end] != ")":
        return None
    return _hangul_run(text, start - 2, -1) or None


def paren_choice(before: str, code: str, label: str) -> str:
    """붙은 괄호 속 코드 처리 — "keep"(코드 그대로) · "drop"(괄호째 지움) · "label"(괄호에 표기).

    before = 여는 괄호 앞 본문. 앞말이 표기·별칭과 낱말 경계까지 같을 때만 drop.
    """
    if label.endswith(f"({code})"):
        return "keep"  # 유형·통화 — v2 말 + 코드
    for same in (label, *PAREN_ALIASES.get(code, ())):
        if before.endswith(same) and not (len(before) > len(same) and _is_hangul(before[-len(same) - 1])):
            return "drop"
    return "label"


def _final(label: str) -> str | None:
    base = label[: label.rfind("(")] if label.endswith(")") and "(" in label else label
    base = base.rstrip()
    return base[-1] if base and _is_hangul(base[-1]) else None


def particle_fix(text: str, cursor: int, label: str) -> tuple[str, int]:
    """cursor(바꾼 표기 바로 뒤)의 조사 하나가 받침과 안 맞으면 (맞는 조사, 바꿀 길이), 아니면 ("", 0)."""
    run = _hangul_run(text, cursor, 1)
    final = _final(label)
    if final is None:
        return "", 0
    jong = _jong(final)
    for with_jong, without in PARTICLE_PAIRS:
        if run not in (with_jong, without):
            continue
        want = with_jong if jong else without
        if with_jong == "으로" and jong == RIEUL:
            want = without
        return (want, len(run)) if want != run else ("", 0)
    return "", 0


def tidy(text: str, plain_labels: set[str]) -> str:
    """같은 말 괄호·겹친 "자료 없음"을 하나로(멱등)."""
    for label in sorted(plain_labels, key=len, reverse=True):
        text = re.sub(rf"(?<![가-힣]){re.escape(label)}\({re.escape(label)}\)", label, text)  # 낱말 경계
    return REPEATED_ABSENCE.sub(r"\1\2 없음", text)
