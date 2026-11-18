"""SCRUM-146 검색어 만들기 (docs/str/10 "다중 질의·합치기"). 순수 — DB·LLM·설정 0.

(a) 지금 `build_query(facts)` 그대로(첫 번째 = 기준선 질의) · (b) `TYPOLOGY_PATTERN_EN[유형]` 만 ·
(c) facts 범주 영문 한 문장(`constants_rag_query` — 숫자·계좌·금액 0, 쓸 조각이 없으면 없음).
상한 `RAG_MAX_QUERIES`. `TYPOLOGY_KO`·`TYPOLOGY_PATTERN_EN`·`build_query` 는 `infrastructure/retriever.py`
에서 여기로 옮김(문장 0 변경 — retriever 는 같은 이름을 다시 내보냄).
"""

from __future__ import annotations

from dataclasses import dataclass

from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain.constants import RAG_MAX_QUERIES
from aml_ai.str.domain.constants_rag_query import (
    COUNTERPARTY_EN,
    COUNTERPARTY_FEW_MAX,
    COUNTERPARTY_SEVERAL_MAX,
    DIRECTION_EN,
    MULTI_CURRENCY_EN,
    OTHER_BANKS_EN,
    PAYMENT_FORMAT_EN,
    QUERY_KINDS,
    QUERY_LANG_EN,
)

TYPOLOGY_KO = {  # 앞 6개 = v2 룰 순서(Typology 와 같게), 뒤 = 원천·후보 값
    "FAN_OUT": "분산 송금",
    "FAN_IN": "집중 입금",
    "FX_RELAY": "환전 중계",
    "CYCLE": "순환 거래",
    "SCATTER_GATHER": "흩었다 모으기",
    "GATHER_SCATTER": "모았다 흩기",
    "PASS_THROUGH": "경유 송금",
    "STACK": "다단계 경유",
    "BIPARTITE": "집단 간 교차 송금",
    "STRUCTURING": "분할 거래",
    "NEW_ACCOUNT_LARGE": "신규 계좌 거액 송금",
    "HIGH_VALUE": "고액 단건",
    "DORMANT_BURST": "휴면 후 급증",
}

# SCRUM-126 — 유형별 영문 패턴 한 문장. 코퍼스가 영문이라 유형 이름만으로는 임베딩 매칭이 약함.
# ★L-1 baseline(유형 이름만 + model_signals): FAN_OUT·CYCLE hit 0, FAN_IN precision 0.33.
TYPOLOGY_PATTERN_EN = {
    "FAN_IN": "many senders deposit into one account",
    "FAN_OUT": "one account sends funds to many beneficiaries",
    "CYCLE": "funds move through accounts and return to the originating account",
    "SCATTER_GATHER": "funds are split across intermediate accounts and later consolidated into one account",
    "GATHER_SCATTER": "funds are pooled into one account and then distributed to many accounts",
}


@dataclass(frozen=True)
class SearchQuery:
    kind: str  # "a" | "b" | "c"
    lang: str  # "en" | "ko" — 벡터 검색은 "en" 만
    text: str


def build_query(facts: Facts) -> str:
    """'{유형 한국어} {유형 영문 코드} {영문 패턴} {model_signals 이름} {industry}'.

    SCRUM-126 — 유형별 영문 패턴 한 문장 추가 (코퍼스 임베딩과 매칭 강화).
    """
    code = facts.typology.value if facts.typology else ""
    pattern = TYPOLOGY_PATTERN_EN.get(code, "")
    signals = " ".join(facts.model_signals)
    industry = facts.customer.industry if facts.customer and facts.customer.industry else ""
    return " ".join(p for p in (TYPOLOGY_KO.get(code, ""), code, pattern, signals, industry) if p)


def facts_query_en(facts: Facts) -> str | None:
    """(c) — 방향 · 상대 수 규모 · 결제 방식 · 타행 · 여러 통화 조각을 이 순서로 이어 한 문장. 조각 0 이면 None."""
    fragments = []
    direction = DIRECTION_EN.get(facts.direction)
    if direction:
        fragments.append(direction)
    count = facts.counterparties.count
    if count:
        scale = (
            "few"
            if count <= COUNTERPARTY_FEW_MAX
            else ("several" if count <= COUNTERPARTY_SEVERAL_MAX else "many")
        )
        fragments.append(COUNTERPARTY_EN[scale])
    payments = [PAYMENT_FORMAT_EN[p] for p in facts.payment_formats if p in PAYMENT_FORMAT_EN]
    if payments:
        fragments.append("via " + " and ".join(payments))
    if facts.counterparty_banks.other_bank_accounts > 0:
        fragments.append(OTHER_BANKS_EN)
    currencies = {c.currency for c in facts.inbound.by_currency + facts.outbound.by_currency}
    if len(currencies) >= 2 or facts.unmapped_currencies:
        fragments.append(MULTI_CURRENCY_EN)
    return ", ".join(fragments) or None


def build_queries(facts: Facts, kinds: tuple[str, ...] = QUERY_KINDS) -> list[SearchQuery]:
    """`kinds` 순서대로(늘 "a" 포함), 문장이 없는 종류는 빠짐, 같은 문장은 한 번, 상한 `RAG_MAX_QUERIES`."""
    if "a" not in kinds:
        raise ValueError("query kinds must include a")
    code = facts.typology.value if facts.typology else ""
    texts = {"a": build_query(facts), "b": TYPOLOGY_PATTERN_EN.get(code), "c": facts_query_en(facts)}
    queries: list[SearchQuery] = []
    seen: set[str] = set()
    for kind in kinds:
        sentence = texts[kind]
        if sentence and sentence not in seen:
            queries.append(SearchQuery(kind, QUERY_LANG_EN, sentence))
            seen.add(sentence)
        if len(queries) >= RAG_MAX_QUERIES:
            break
    return queries
