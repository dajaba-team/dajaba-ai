"""DATE_MATCH 개설 단어 위치·`거래 시작` 신호 판정 (docs/str/06 DATE_MATCH 줄 ②, SCRUM-290 2/2 추가 검토 1·2). 순수 함수.

`ONBOARD_WORDS` 는 늘 개설 단어. `거래 시작` 은 신호로 나눈다 — 개설 신호(바로 뒤 `일`·앞 10자 `고객`) 둘 다이고
기간 신호(바로 뒤 `일시`·날짜에 시각·같은 절 `기간`/`부터`/`까지`)가 없으면 개설일, 개설 신호가 없으면 거래 날짜,
그 밖(하나만·충돌)은 UNPARSED — 애매하면 추측하지 않는다(06).
`거래 시작` 바로 앞에서 꾸미는 입금·출금 같은 방향 낱말이면 먼저 거래 날짜(추가 검토 3·4).
"""

from __future__ import annotations

import unicodedata

from aml_ai.str.domain.constants import (
    DATE_CONTEXT_WINDOW,
    DIRECTION_IN_WORDS,
    DIRECTION_INTERNAL_WORDS,
    DIRECTION_OUT_WORDS,
    ONBOARD_CUSTOMER_WORD,
    ONBOARD_WORDS,
    TRADE_START_ONBOARD_SUFFIX,
    TRADE_START_PERIOD_SUFFIX,
    TRADE_START_PERIOD_WORDS,
    TRADE_START_WORD,
)

_DIRECTION_WORDS = (*DIRECTION_IN_WORDS, *DIRECTION_OUT_WORDS, *DIRECTION_INTERNAL_WORDS)


def onboard_word_spans(text: str) -> list[tuple[int, int, bool]]:
    """text 속 개설 단어 후보 [시작, 끝, `거래 시작` 여부]. `ONBOARD_WORDS` 순서 뒤 `거래 시작`."""
    spans = [(i, i + len(w), False) for w in ONBOARD_WORDS for i in find_all(text, w)]
    spans += [(i, i + len(TRADE_START_WORD), True) for i in find_all(text, TRADE_START_WORD)]
    return spans


def trade_start_verdict(text: str, start: int, end: int, *, has_time: bool) -> str:
    """`거래 시작` 이 가장 가까운 날짜에 대해 "ONBOARD" · "TRANSACTION" · "UNPARSED".

    거래 방향 낱말(COUNT 검사기 목록 재사용)이 `거래 시작` 바로 앞에서 꾸미면(같은 줄 공백·탭) 거래 흐름 — 개설 신호와
    무관하게 TRANSACTION. 같은 절 다른 곳의 방향 낱말은 안 본다(추가 검토 4).
    """
    if _direction_modifies(text[:start]):
        return "TRANSACTION"
    after = text[end:]
    day = after.startswith(TRADE_START_ONBOARD_SUFFIX) and not after.startswith(TRADE_START_PERIOD_SUFFIX)
    customer = ONBOARD_CUSTOMER_WORD in text[max(0, start - DATE_CONTEXT_WINDOW) : start]
    period = (
        after.startswith(TRADE_START_PERIOD_SUFFIX)
        or has_time
        or any(w in text for w in TRADE_START_PERIOD_WORDS)
    )
    onboard_signals = int(day) + int(customer)
    if onboard_signals == 0:
        return "TRANSACTION"
    if onboard_signals == 2 and not period:
        return "ONBOARD"
    return "UNPARSED"


def _direction_modifies(before: str) -> bool:
    """`거래 시작` 앞 글자가 방향 낱말 + 수평 공백 묶음(0개 이상)으로 끝나는가(추가 검토 5·6).

    수평 공백 = 유니코드 범주 Zs(일반·NBSP·전각·U+2000대 등) + 탭. 줄 경계(`LINE_BREAK_CHARS`)는 Zs 가 아니라
    지우지 않는다 — 절 나누기에서 이미 경계.
    """
    end = len(before)
    while end > 0 and _is_horizontal_space(before[end - 1]):
        end -= 1
    return before[:end].endswith(_DIRECTION_WORDS)


def _is_horizontal_space(ch: str) -> bool:
    return ch == "\t" or unicodedata.category(ch) == "Zs"


def find_all(text: str, word: str) -> list[int]:
    out: list[int] = []
    start = 0
    while (i := text.find(word, start)) != -1:
        out.append(i)
        start = i + 1
    return out
