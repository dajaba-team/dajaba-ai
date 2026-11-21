"""SCRUM-146 검색어 (c) facts 범주 영문 조각 (docs/str/10 "다중 질의·합치기" ★A 표 — 쓰는 칸 5개만).

숫자·계좌·금액 없음. 표에 없는 칸(경로·내부 거래·계좌 목적)은 보류라 여기 없음.
`constants.py` 가 200줄 한도에 닿아 따로 둠.
"""

from __future__ import annotations

QUERY_KINDS: tuple[str, ...] = ("a", "b", "c")  # (a) build_query 그대로 · (b) 유형 패턴 · (c) facts 범주
QUERY_LANG_EN = "en"
QUERY_LANG_KO = "ko"  # 모양만 — 벡터 검색은 영문만 보냄

DIRECTION_EN: dict[str, str] = {  # Direction → 조각. INTERNAL 은 코퍼스 대응 문단 없음 → 없음
    "INBOUND": "incoming funds only",
    "OUTBOUND": "outgoing funds only",
    "MIXED": "both incoming and outgoing funds",
}
COUNTERPARTY_FEW_MAX = 2  # 1~2 few · 3~9 several · 10 이상 many (검색어 전용 — 룰 임계값과 따로)
COUNTERPARTY_SEVERAL_MAX = 9
COUNTERPARTY_EN: dict[str, str] = {
    "few": "few counterparties",
    "several": "several counterparties",
    "many": "many counterparties",
}
PAYMENT_FORMAT_EN: dict[str, str] = {  # IBM 원문 7종. Reinvestment 는 코퍼스 대응 낱말 없음 → 없음
    "Wire": "wire transfers",
    "ACH": "ACH transfers",
    "Cash": "cash",
    "Cheque": "cheques",
    "Credit Card": "credit card payments",
    "Bitcoin": "virtual currency",
}
OTHER_BANKS_EN = "accounts at other financial institutions"  # other_bank_accounts > 0
MULTI_CURRENCY_EN = "multiple currencies"  # 통화 종류(입금 ∪ 출금 by_currency) ≥ 2 또는 미등록 통화 있음

# ---- SCRUM-275 빈칸만 채우기 · ES 키워드 (docs/str/10 "빈칸만 채우기")
QUERY_KIND_KEYWORD = "kw"  # 키워드 검색어 종류 — 벡터 검색어 (a)(b)(c) 와 따로
KEYWORD_FIELDS: dict[str, str] = {QUERY_LANG_EN: "text_en", QUERY_LANG_KO: "text_ko"}  # 언어 → ES 본문 필드
KEYWORD_ANALYZERS: dict[str, str] = {
    QUERY_LANG_EN: "english",
    QUERY_LANG_KO: "cjk",
}  # nori 는 이미지에 없음 → 2차
ES_BULK_BATCH = 200  # 색인 도구 _bulk 한 번에 보낼 청크 수
ES_ADMIN_TIMEOUT_S = 30.0  # 색인 도구(색인 만들기·_bulk) 타임아웃 — 검색 타임아웃은 ELASTIC_TIMEOUT_S

# SCRUM-308-2 리랭커 (docs/str/10 "리랭커", 05 "rerank_v1")
RERANK_PROMPT = "rerank_v1"
RERANK_LABEL_PREFIX = "C"  # 후보 표지 C1~Cn — 64자 chunk_id 대신(코드가 되돌림)
RAG_RERANK_MAX_TOKENS = 1000  # 추론 모델은 추론 토큰도 이 안 — 짧으면 형식 실패가 늘어남
RERANK_MIN_CANDIDATES = 2  # 후보가 이보다 적으면 줄 세울 게 없어 LLM 호출 0
RAG_RERANK_TIMEOUT_MAX_S = (
    8.0  # 운영 상한(기동 검사) — 308 기준 ② 판정 한도와 같음. 8 이하는 허용(짧으면 폴백만 늘어남)
)

# SCRUM-308-3 청크 맥락 — 머리말 형식 버전(`retrieval_version` 꼬리 `+ctx:v1`) · 검색 표(str/10 "청크 맥락")
CHUNK_CONTEXT_VERSION = "v1"
REFERENCE_TABLE = "ai.reference_chunks"
REFERENCE_CTX_TABLE = "ai.reference_chunks_ctx"
REFERENCE_TABLES = (REFERENCE_TABLE, REFERENCE_CTX_TABLE)
