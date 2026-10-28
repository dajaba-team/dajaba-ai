"""이름 붙인 상수. 코드 다른 곳에 숫자·정규식이 보이면 여기로 옮긴다 (docs/str/01)."""

from __future__ import annotations

import re
from decimal import Decimal

# ---- facts (docs/str/04)
# IBM 원천 통화 이름 → ISO 4217 코드. Bitcoin→BTC 는 규약 0절 예외. 표에 없는 이름은 UnknownCurrency.
CURRENCY_CODES: dict[str, str] = {
    "US Dollar": "USD",
    "Euro": "EUR",
    "Yuan": "CNY",
    "Shekel": "ILS",
    "Canadian Dollar": "CAD",
    "UK Pound": "GBP",
    "Ruble": "RUB",
    "Australian Dollar": "AUD",
    "Swiss Franc": "CHF",
    "Yen": "JPY",
    "Mexican Peso": "MXN",
    "Rupee": "INR",
    "Brazil Real": "BRL",
    "Saudi Riyal": "SAR",
    "Bitcoin": "BTC",
}
DIRECTION_RATIO = 2  # inbound ≥ 2 × outbound → INBOUND (진희 가정값, 축소본 분포 뒤 조정)
MONEY_QUANT = Decimal("0.01")
PATH_RULE_KIND: dict[str, str] = {"R04_CYCLE": "CYCLE", "R05_STACK": "STACK"}  # rule_id → paths.kind
PATH_MIN_TRANSACTIONS = 2
MODEL_SIGNALS_TOP = 3  # reasons 상위 N개의 이름만 model_signals 로

# ---- 프롬프트 (docs/str/05)
NARRATIVE_PROMPT = "narrative_v1"
JUDGE_PROMPT = "judge_v1"
SUMMARY_PROMPT = "summary_v1"
LLM_TEMPERATURE = 0.0
NARRATIVE_MAX_TOKENS = 2000
JUDGE_MAX_TOKENS = 1200
FEWSHOT_SAME_TYPOLOGY = 1
FEWSHOT_OTHER_TYPOLOGY = 2
SCHEMA_RETRY = 1  # 스키마 실패 시 재생성 횟수 (재시도가 아니라 생성 절차의 일부)

# ---- 검증 (docs/str/06)
VERIFIER_VERSION = "verify-2026.11"  # 코드 검증 로직이 바뀌면 올린다
JUDGE_PASS_SCORE = 4  # W4 오류 주입 7~12 표 뒤 조정
AMOUNT_CONTEXT_CHARS = 10  # 통화 단어 ±N 자 안의 숫자만 "금액 문맥"
CURRENCY_WORDS = (
    "원",
    "달러",
    "USD",
    "US Dollar",
    "유로",
    "EUR",
    "엔",
    "JPY",
    "위안",
    "CNY",
    "파운드",
    "GBP",
    "루피",
    "INR",
    "레알",
    "BRL",
    "페소",
    "MXN",
    "쉐켈",
    "ILS",
    "프랑",
    "CHF",
    "루블",
    "RUB",
    "리얄",
    "SAR",
    "AUD",
    "CAD",
    "비트코인",
    "BTC",
)
KOREAN_UNIT_MULTIPLIER = {"천만": Decimal(10) ** 7, "억": Decimal(10) ** 8, "만": Decimal(10) ** 4}
RE_AMOUNT = re.compile(r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(천만|억|만)?")
RE_DATE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})|(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일|(?<!\d)(\d{1,2})월\s*(\d{1,2})일|(\d{4})/(\d{2})/(\d{2})"
)
RE_COUNTERPARTY = re.compile(r"(\d+)\s*(?:개|곳|명)의?\s*(?:계좌|상대|거래처)")

# ---- RAG (docs/str/10)
RAG_TOP_K = 3
REFERENCE_TEXT_MAX_CHARS = 600
CHUNK_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
EMBED_BATCH = 64
RECALL_AT_K_MIN = 0.7
