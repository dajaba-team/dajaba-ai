"""AMOUNT_MATCH 통화 표기 상수 (docs/str/06 "AMOUNT_MATCH", SCRUM-58·SCRUM-131).

`constants.py` 가 200줄 한도에 닿아 따로 둠 — 쓰는 곳은 이 모듈에서 이름별로 직접 import.
"""

from __future__ import annotations

from aml_ai.str.domain.constants import (
    BANK_COUNT_UNITS,
    COUNT_UNITS_COUNT,
    COUNT_UNITS_SMALL,
    NON_AMOUNT_TRAILERS,
    PATH_HOP_UNITS,
    PERIOD_UNITS,
)

# 코드 → 표기 목록(SCRUM-131: 국가명 붙은 한국어 이름·표준 표기 헤알·셰켈 추가). 긴 표기부터 매칭하므로 코드·IBM 원문·한국어 전부 수록. 맨 "달러"→USD (★A 2).
# "원"·"₩" 은 facts 에 없어 늘 MISMATCH — 환산 금지 규칙(04).
CURRENCY_ALIASES: dict[str, tuple[str, ...]] = {
    "USD": ("USD", "US Dollar", "미국 달러", "달러", "$"),
    "EUR": ("EUR", "Euro", "유로"),
    "CNY": ("CNY", "Yuan", "위안", "중국 위안"),
    "ILS": ("ILS", "Shekel", "쉐켈", "셰켈", "이스라엘 셰켈", "이스라엘 쉐켈"),
    "CAD": ("CAD", "Canadian Dollar", "캐나다 달러"),
    "GBP": ("GBP", "UK Pound", "영국 파운드", "파운드"),
    "RUB": ("RUB", "Ruble", "루블", "러시아 루블"),
    "AUD": ("AUD", "Australian Dollar", "호주 달러"),
    "CHF": ("CHF", "Swiss Franc", "스위스 프랑", "프랑"),
    "JPY": ("JPY", "Yen", "엔", "일본 엔"),
    "MXN": ("MXN", "Mexican Peso", "멕시코 페소", "페소"),
    "INR": ("INR", "Rupee", "루피", "인도 루피"),
    "BRL": ("BRL", "Brazil Real", "브라질 레알", "레알", "브라질 헤알", "헤알"),
    "SAR": ("SAR", "Saudi Riyal", "사우디 리얄", "리얄", "사우디아라비아 리얄"),
    "BTC": ("BTC", "Bitcoin", "비트코인"),
    "KRW": ("KRW", "원", "₩"),
}

# 안전망 (SCRUM-131 ★A-2) — 금액 숫자 + 한글 낱말 1~2개 + 공백 + 통화 표기 → UNPARSED.
AMOUNT_GAP_WORDS_MAX = 2
AMOUNT_GAP_WORD_MIN_CHARS = 2
AMOUNT_GAP_WORD_MAX_CHARS = 6
# 첫 낱말이 단위면 금액 아님(건수·기간) — 새 목록을 두지 않고 기존 단위 상수를 합침.
AMOUNT_GAP_UNIT_WORDS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            *NON_AMOUNT_TRAILERS,
            *COUNT_UNITS_SMALL,
            *COUNT_UNITS_COUNT,
            *BANK_COUNT_UNITS,
            *PATH_HOP_UNITS,
            *PERIOD_UNITS,
        )
    )
)
# 낱말이 이 조사·어미로 끝나면 통화 이름을 꾸미는 말이 아님(`건을`·`건이며`·`일간`) — 단위 제외보다 먼저.
AMOUNT_GAP_WORD_ENDINGS: tuple[str, ...] = (
    *("을", "를", "은", "는", "이", "가", "의", "에", "로", "으로", "에서", "와", "과", "도", "만"),
    *("이며", "이고", "이고는", "간", "동안", "뒤", "후"),
)
AMOUNT_GAP_STOP_WORDS: tuple[str, ...] = ("기준",)  # `31.0 기준 미국 달러` — 관측·비교 기준 숫자
