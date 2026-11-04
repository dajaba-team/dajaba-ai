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
JUDGE_MAX_TOKENS = 4000
JUDGE_SCHEMA_RETRY = 1
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

# DATE_MATCH (SCRUM-59) — 06 "DATE_MATCH" 줄. 날짜·시각·범위·용도 분류 상수.

# 날짜 형식 — 지원하는 쓰기만 뽑고 그 밖(`아침`·`9월 초`)은 UNPARSED.
# ISO: `YYYY-MM-DD` 또는 `YYYY-MM-DDTHH:MM(:SS)` (녹화 v1·v2 가 실제 쓰는 모양).
RE_DATE_ISO = re.compile(
    # 끝 lookahead `(?![0-9:])` — `22:51:300` 처럼 뒤 `:숫자` 가 더 붙어 있어도 짧은 매치가
    # "완결된 시각" 처럼 통과하지 않게(SCRUM-59 Codex adversarial 3차).
    r"(?<![0-9])(\d{4})-(\d{1,2})-(\d{1,2})(?:[T\s](\d{1,2}):(\d{2})(?::(\d{2}))?)?(?![0-9:])"
)
# `YYYY년 M월 D일` + 선택 시각(`오전/오후 H시 M분` 또는 `HH:MM`).
# 시각은 공용 소비기 `verification_date_time.consume_trailing_time` 가 받음(초 포함).
# regex 자체에 시각 그룹을 두면 분까지만 흡수하고 초가 조용히 버려지는 경로가 생겨 — 통일(SCRUM-59 2차 Codex).
RE_DATE_KO = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
# `M월 D일` — 연도 없음(period.start 연도로 보강).
# `일` 뒤 숫자가 다른 날짜 단위(`\d년`·`\d월`·`\d일`)로 끝나야 거부 — 시각(`23:30`·공백 0) 은 허용.
RE_DATE_KO_NOYEAR = re.compile(r"(?<![0-9년])(\d{1,2})월\s*(\d{1,2})일(?![0-9]*[년월일])")
# `YYYY/MM/DD`
RE_DATE_SLASH = re.compile(r"(?<![0-9])(\d{4})/(\d{1,2})/(\d{1,2})(?![0-9])")
# `YYYY.M.D` — 금액 소수점과 분리하려고 양옆 아닌 숫자 확인.
RE_DATE_DOT = re.compile(r"(?<![0-9])(\d{4})\.(\d{1,2})\.(\d{1,2})(?![0-9])")

# 시각만(`HH:MM` 또는 `HH:MM:SS`) — 날짜와 쌍일 때만 쓰려고 미리 뽑아 둠.
RE_TIME_HHMM = re.compile(r"(?<![0-9])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![0-9])")

# 날짜 모양이지만 못 읽는 표현 — UNPARSED 로 떨어뜨림.
VAGUE_DATE_SUFFIXES: tuple[str, ...] = ("초", "중순", "말", "중")  # `9월 초`·`9월 중순`·`9월 중`
# 월만 — `YYYY년 M월`(일 없음) → UNPARSED. ("YYYY년 M월 D일" 과 겹치지 않게 lookbehind.)
RE_YEAR_MONTH_ONLY = re.compile(r"(\d{4})년\s*(\d{1,2})월(?!\s*\d+일)(?![0-9])")

# 날짜 바로 뒤 시간대 단어 → UNPARSED (`9월 2일 아침`·`9월 2일 오전에` — ★A 4 유지).
# `오전 11시`·`오후 2시` 는 공용 소비기 `verification_date_time.consume_trailing_time` 가
# 먼저 받으므로 UNPARSED 안 됨 — 소비기가 "none" 일 때만(숫자 시각 없이 단어만) 이 집합 체크.
TIME_OF_DAY_WORDS: tuple[str, ...] = ("아침", "점심", "저녁", "새벽", "밤", "오전", "오후")

# 날짜 용도 분류 (★A 1·2).
# ONBOARD_WORDS — ±DATE_CONTEXT_WINDOW 자 안 가장 가까운 날짜가 개설일 용도.
ONBOARD_WORDS: tuple[str, ...] = ("개설", "가입", "신규", "거래 시작")
DATE_CONTEXT_WINDOW = 10  # 글자 수(코드포인트)

# OBSERVATION_WORDS — 괄호 안 또는 여는 괄호 바로 앞(공백 제외)에 있으면 observation 용도.
# `관측값`·`관측 구간` 둘 다 매칭 — `관측` substring 포함.
OBSERVATION_WORDS: tuple[str, ...] = ("관측값", "관측 구간", "관측")

# COUNT_MATCH (SCRUM-60, 06). 절 분리: 양옆 모두 숫자인 쉼표·소수점만 보존, 그 밖 분리(adv. 3차).
COUNT_CLAUSE_SPLIT = re.compile(r"(?<!\d)[.,;]|[.,;](?!\d)|\n")
PRIOR_ALERT_WORDS: tuple[str, ...] = ("과거 경보", "이전 경보", "앞서 경보")
COUNT_OBSERVATION_WORDS: tuple[str, ...] = ("관측", "모델")  # DATE 와 별개(DATE 동작 안 바꿈)
PATH_WORDS: tuple[str, ...] = ("경로", "고리", "순환")
PATH_HOP_UNITS: tuple[str, ...] = ("홉", "단계")  # PATH_HOPS 전용, PATH 와 별개(adv. 3차)
PERIOD_UNITS: tuple[str, ...] = ("시간", "일", "주", "개월", "년")  # 관측 소비 시 건너뜀(adv. 4차)
COUNTERPARTY_WORDS: tuple[str, ...] = ("상대방", "상대", "거래처", "송금인", "수취인", "계좌")
SAME_BANK_WORDS: tuple[str, ...] = ("자행", "같은 은행", "동일 은행")
OTHER_BANK_WORDS: tuple[str, ...] = ("타행", "다른 은행")
DIRECTION_IN_WORDS: tuple[str, ...] = ("입금", "받은", "수취")
DIRECTION_OUT_WORDS: tuple[str, ...] = ("보낸", "출금")  # `송금` 뺌(SCRUM-60 ★A 3)
DIRECTION_INTERNAL_WORDS: tuple[str, ...] = ("법인 내", "내부")
PAYMENT_FORMAT_ALIASES: dict[str, tuple[str, ...]] = {
    "ACH": ("ACH",),
    "Wire": ("Wire", "전신환"),
    "Cash": ("Cash", "현금"),
    "Credit Card": ("Credit Card", "신용카드"),
    "Cheque": ("Cheque", "수표"),
    "Reinvestment": ("Reinvestment", "재투자"),
}
# 한글 수사 + 단위 → UNPARSED. `한`(1)은 "한 계좌로" 관용이라 제외.
KOREAN_NUMERAL_COUNT: frozenset[str] = frozenset(
    ("두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉")
    + ("열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔")
)
COUNT_UNITS_SMALL: tuple[str, ...] = ("개", "곳", "명")  # 상대·경로·자행/타행·관측값
COUNT_UNITS_COUNT: tuple[str, ...] = ("건", "회")  # 과거·관측값·결제·거래 건수
BANK_COUNT_UNITS: tuple[str, ...] = ("개", "곳", "계좌")  # ⑦ 자행/타행 뒤 단위

# ---- RAG (docs/str/10)
RAG_TOP_K = 3
REFERENCE_TEXT_MAX_CHARS = 600
CHUNK_TOKENS = 500
CHUNK_OVERLAP_TOKENS = 50
EMBED_BATCH = 64
RECALL_AT_K_MIN = 0.7
