"""SCRUM-126 ★L-2 — 초안 본문에서 facts·fact_keys·화면 고정 문구 밖 **숫자·고유명 후보 수** 집계.

판정 기준 (보수적 heuristic — 완벽 X, 방향성 근거):
1) **숫자 후보**: 본문에서 `\\b\\d[\\d,]*\\.?\\d*\\b` 매칭 → 쉼표 제거 정규화 → 두 집합과 비교
   - **facts 안 모든 숫자 값·문자열 값**(subject·금액·count·observations·amount_range·prior_alert_count 등)
   - **화면 고정 숫자**: 0~24 (시각·주·일·개수), 1~12 (월), 1~31 (일), 2000~2099 (연도)
2) **고유명 후보**: `\\b[A-Z][a-zA-Z]{1,}\\b` 매칭 → 두 집합과 비교
   - **facts 문자열 전체** (대소문자 무관 `in` 비교 — `Portugal Bank #4507` 안 `Portugal` 매칭 OK)
   - **fact_keys 이름** (`inbound.by_currency[0].total` 등)
   - **아래 FIXED_NAMES** 상수 (섹션·유형·통화·공통 용어·부재 표기)

예외 목록 (FIXED_NAMES):
- 섹션 이름 v1·v2: SUMMARY·WHO·WHAT_WHEN_WHERE·HOW·WHY_SUSPICIOUS·CONCLUSION·SUBJECT·DATE·PLACE·INSTRUMENT·METHOD·GROUNDS·OPINION
- 유형 코드 12종: FAN_IN·FAN_OUT·CYCLE·PASS_THROUGH·SCATTER_GATHER·GATHER_SCATTER·STACK·BIPARTITE·STRUCTURING·NEW_ACCOUNT_LARGE·HIGH_VALUE·DORMANT_BURST
- 통화 코드 (CURRENCY_ALIASES 15종): USD·EUR·KRW·JPY·CNY·GBP·HKD·INR·MXN·CAD·AUD·CHF·BTC·SAR·AED
- 보고서 공통 용어: STR·AML·FACTS·NOTES·REFERENCES·ACH·SWIFT·BSA·KYC·CDD

반환은 **개수만** — 토큰 자체는 JSON·로그에 안 담음(CLAUDE.md 로그 금지어 준수).
"""

from __future__ import annotations

import re
from typing import Any

from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain.fact_keys import fact_keys as _fact_keys_fn

NUMBER_RE = re.compile(r"\b\d[\d,]*\.?\d*\b")
PROPER_RE = re.compile(r"\b[A-Z][a-zA-Z]{1,}\b")

FIXED_NAMES: set[str] = {
    # 섹션 이름 (v1·v2)
    "SUMMARY", "WHO", "WHAT_WHEN_WHERE", "HOW", "WHY_SUSPICIOUS", "CONCLUSION",
    "SUBJECT", "DATE", "PLACE", "INSTRUMENT", "METHOD", "GROUNDS", "OPINION",
    # 유형 코드 12종
    "FAN_IN", "FAN_OUT", "CYCLE", "PASS_THROUGH", "SCATTER_GATHER", "GATHER_SCATTER",
    "STACK", "BIPARTITE", "STRUCTURING", "NEW_ACCOUNT_LARGE", "HIGH_VALUE", "DORMANT_BURST",
    # 통화 코드 15종
    "USD", "EUR", "KRW", "JPY", "CNY", "GBP", "HKD", "INR", "MXN", "CAD",
    "AUD", "CHF", "BTC", "SAR", "AED",
    # 보고서 공통
    "STR", "AML", "FACTS", "NOTES", "REFERENCES", "ACH", "SWIFT", "BSA", "KYC", "CDD",
}  # fmt: skip


def _facts_strings(facts: Facts) -> set[str]:
    """Facts 안 모든 리프 값을 문자열로 — 숫자·문자열·bool 포함."""
    out: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif x is None or isinstance(x, bool):
            return
        else:
            out.add(str(x))

    walk(facts.model_dump(mode="json"))
    return out


def _is_common_number(tok: str) -> bool:
    """화면 고정 숫자 — 시각(0~24)·일(1~31)·월(1~12)·연도(2000~2099)."""
    try:
        v = float(tok.replace(",", ""))
    except ValueError:
        return False
    if v != int(v):
        return False
    iv = int(v)
    return 0 <= iv <= 24 or 2000 <= iv <= 2099


def _number_in_facts(tok: str, facts_strs: set[str]) -> bool:
    """쉼표 제거 정규화 뒤 facts 문자열 어딘가에 포함되면 True."""
    norm = tok.replace(",", "")
    return any(norm in s.replace(",", "") for s in facts_strs)


def _name_in_facts(name: str, facts_strs: set[str]) -> bool:
    """대소문자 무관 `in` 비교 — facts 안 긴 문자열에 포함되면 True."""
    lo = name.lower()
    return any(lo in s.lower() for s in facts_strs)


def unsupported_candidate_count(narrative: list, facts: Facts) -> int:
    """`narrative` 본문에서 facts·fact_keys·FIXED_NAMES 밖 숫자·고유명 **후보 수**.

    토큰 자체는 반환하지 않음 — 결과 JSON·로그에 담기지 않게.
    """
    text = " ".join(s.text for s in narrative)
    facts_strs = _facts_strings(facts)
    fact_key_names = set(_fact_keys_fn(facts).keys())

    number_tokens = set(NUMBER_RE.findall(text))
    name_tokens = set(PROPER_RE.findall(text))

    unsupported_nums = {
        n for n in number_tokens
        if not _is_common_number(n) and not _number_in_facts(n, facts_strs)
    }  # fmt: skip
    unsupported_names = {
        n for n in name_tokens
        if n not in FIXED_NAMES
        and n not in fact_key_names
        and not _name_in_facts(n, facts_strs)
    }  # fmt: skip
    return len(unsupported_nums) + len(unsupported_names)
