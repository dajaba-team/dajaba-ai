"""이름 붙인 상수. 코드 다른 곳에 숫자·정규식이 보이면 여기로 옮긴다 (docs/str/01)."""

from __future__ import annotations

import re
from decimal import Decimal

# ---- facts (docs/str/04)
# IBM 원천 통화 이름 → ISO 4217 코드. Bitcoin→BTC 는 규약 0절 예외.
# 표에 없는 이름은 에러 아님 — Facts.unmapped_currencies 로 원문 보존(SCRUM-47, 미결 7).
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
# NARRATIVE_PROMPT 상수는 폐기 (SCRUM-47) — 활성 서술 버전은 shared/config.narrative_prompt 설정으로.
# tools.record 와 draft_service.build() 는 get_settings().narrative_prompt 를 쓴다.
JUDGE_PROMPT = "judge_v1"
SUMMARY_PROMPT = "summary_v1"
LLM_TEMPERATURE = 0.0
NARRATIVE_MAX_TOKENS = 2000
JUDGE_MAX_TOKENS = 1200
FEWSHOT_SAME_TYPOLOGY = 1
FEWSHOT_OTHER_TYPOLOGY = 2
SCHEMA_RETRY = 1  # 스키마 실패 시 재생성 횟수 (재시도가 아니라 생성 절차의 일부)

# ---- 동결 (docs/str/05 "버전·동결 규칙", docs/shared/04)
# 녹화를 처음 커밋할 때 그 커밋에서 파일 sha256 을 여기에 박는다. 기동 때 파일 해시가
# 이 값과 다르면 실패 — DB 없이도 걸림(SCRUM-15 10/29).
FROZEN_PROMPTS: dict[str, str] = {
    "narrative_v1": "d2cbb854386dd3c01dc0d71556878e1e1287cab540839c56ae7dc51281155424",
    "narrative_v2": "66210c3d25e59b136f4ec2359ad2f09c43501435322874f0048192795653aa9f",
}

# ---- 검증 (docs/str/06)
VERIFIER_VERSION = "verify-2026.11"  # 코드 검증 로직이 바뀌면 올린다
JUDGE_PASS_SCORE = 4  # W4 오류 주입 7~12 표 뒤 조정
# AMOUNT_MATCH (SCRUM-58) — 06 "AMOUNT_MATCH" 줄. ±10자 창 폐기, "바로 붙은 덩이" 기준.
# 코드 → 표기 목록. 긴 표기부터 매칭하므로 코드·IBM 원문·한국어 전부 수록. 맨 "달러"→USD (★A 2).
# "원"·"₩" 은 facts 에 없어 늘 MISMATCH — 환산 금지 규칙(04).
CURRENCY_ALIASES: dict[str, tuple[str, ...]] = {
    "USD": ("USD", "US Dollar", "미국 달러", "달러", "$"),
    "EUR": ("EUR", "Euro", "유로"),
    "CNY": ("CNY", "Yuan", "위안"),
    "ILS": ("ILS", "Shekel", "쉐켈"),
    "CAD": ("CAD", "Canadian Dollar", "캐나다 달러"),
    "GBP": ("GBP", "UK Pound", "영국 파운드", "파운드"),
    "RUB": ("RUB", "Ruble", "루블"),
    "AUD": ("AUD", "Australian Dollar", "호주 달러"),
    "CHF": ("CHF", "Swiss Franc", "스위스 프랑", "프랑"),
    "JPY": ("JPY", "Yen", "엔"),
    "MXN": ("MXN", "Mexican Peso", "멕시코 페소", "페소"),
    "INR": ("INR", "Rupee", "루피"),
    "BRL": ("BRL", "Brazil Real", "브라질 레알", "레알"),
    "SAR": ("SAR", "Saudi Riyal", "사우디 리얄", "리얄"),
    "BTC": ("BTC", "Bitcoin", "비트코인"),
    "KRW": ("KRW", "원", "₩"),
}

RE_AMOUNT_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

# 한국어 복합 단위 — 큰 쪽부터 내려가며 합산. 외는 UNPARSED (★A 3).
KOREAN_UNIT_MULTIPLIER: dict[str, Decimal] = {
    "억": Decimal(10) ** 8,
    "천만": Decimal(10) ** 7,
    "만": Decimal(10) ** 4,
}
# 지원 안 하는 단위가 아라비아 숫자 뒤에 바로 붙으면 UNPARSED (`3천`·`500백만`·`1조`).
UNSUPPORTED_AMOUNT_UNITS: tuple[str, ...] = ("백만", "십만", "조", "경", "천")

# 근사·범위 수식어 — 금액 덩이 바로 앞/뒤에 붙으면 UNPARSED (★A 3).
APPROXIMATE_WORDS: tuple[str, ...] = (
    "약",
    "대략",
    "가량",
    "정도",
    "여",
    "이상",
    "이하",
    "넘는",
    "미만",
    "내외",
)

# 한글 수사 — 수사 글자 2자 이상이고 억·천만·만·천·백·십 중 하나 포함이면 UNPARSED (★A 3·★B).
# "US Dollar이며" 의 조사 '이' 는 2자 미만이라 수사로 안 봄.
KOREAN_NUMERAL_SMALL: frozenset[str] = frozenset("일이삼사오육칠팔구")
KOREAN_NUMERAL_TENS: frozenset[str] = frozenset(
    ("십", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔")
)
KOREAN_NUMERAL_BIG: frozenset[str] = frozenset(("백", "천", "만", "억"))

# 금액 모양 제외 — 숫자 바로 뒤에 이게 오면 건수·날짜 (★B 추가).
NON_AMOUNT_TRAILERS: tuple[str, ...] = ("건", "회", "개", "곳", "명", "년", "월", "일", "시", "분")

# ACCOUNT_ID_MATCH (SCRUM-58) — 06 "ACCOUNT_ID_MATCH" 줄. 세 패턴, 긴 쪽 우선.
RE_ACCOUNT_FULL = re.compile(r"(?<![0-9A-Za-z])\d{1,4}_[0-9A-Z*]{4,}")
RE_ACCOUNT_MASKED_TAIL = re.compile(r"(?<![0-9A-Za-z*])\*{4}[0-9A-Z]{4}")
RE_ACCOUNT_TAIL_KO = re.compile(r"끝자리\s*([0-9A-Z]{4})")

# (DATE·COUNT 정규식은 SCRUM-59·60 구현 때 추가)

# ---- RAG (docs/str/10)
RAG_TOP_K = 3
REFERENCE_TEXT_MAX_CHARS = 600
CHUNK_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
EMBED_BATCH = 64
RECALL_AT_K_MIN = 0.7
