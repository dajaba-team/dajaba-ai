"""SCRUM-309 참고 사례 검색 — 질의 문장 · 결과 정리 (순수, docs/str/10 "참고 사례 검색").

질의 = 고른 유형의 영문 패턴을 정해진 순서로 이어 붙인 한 줄 + (있으면) 가린 검색어. 가린 뒤 공백만 남으면 유형만.
정리 = `MIN_SIMILARITY` 미만 제외(추가 검토 1) → 점수 내림차순(동점 chunk_id) → chunk_id 중복 제거 → 한 문서 최대 n건 → 앞 top_k. 모자라면 있는 만큼.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from aml_ai.str.domain.ask_question import mask_question
from aml_ai.str.domain.constants import MIN_SIMILARITY
from aml_ai.str.domain.rag_queries import TYPOLOGY_PATTERN_EN

TYPOLOGY_ORDER = ("FAN_IN", "FAN_OUT", "CYCLE", "SCATTER_GATHER", "GATHER_SCATTER")
# 검색용 가리기 — `mask_question` 보다 먼저, 아래 순서(추가 검토 1~3, 실패 쪽으로 닫음). 조각 사이 구분자는 `-`·공백(탭·줄바꿈
# 포함)·`.` 연속 최대 3글자(`1234 - 5678` 의 " - ") — 문장 속 멀리 떨어진 숫자까지 잇지 않게(검토 2)
_SEP_MAX = 3
_SEP = rf"[-.\s]{{1,{_SEP_MAX}}}"
_HYPHENS = re.compile(
    "[\u2010-\u2015\u2212\ufe58\ufe63\uff0d]"
)  # 하이픈·대시 변형 → `-`(검토 3, NFKC 로 안 바뀌는 것 포함)
_SEG = "(?:[0-9A-Fa-f]+|(?=[A-Za-z]*[0-9])[0-9A-Za-z]+)(?![0-9A-Za-z])"  # 이어 붙일 조각 = 16진 글자만 or 숫자 포함
_BANK_KEY = re.compile(rf"(?<![0-9A-Za-z_*])([0-9]{{1,4}})_([0-9A-Za-z]+(?![0-9A-Za-z])(?:{_SEP}{_SEG})*)")
_HEX = "[0-9A-Fa-f]+(?![0-9A-Za-z])"
_HEX_RUN = re.compile(rf"(?<![0-9A-Za-z_*]){_HEX}(?:{_SEP}{_HEX})*")  # 16진 나뉜 계좌(`8000-EBD-30`)
_DIGIT_RUN = re.compile(rf"\d(?:[-.\s]{{0,{_SEP_MAX}}}\d)+")
_DIGITS_MIN = 8
_HEX_MIN = 8
_HEX_DIGITS_MIN = 4
_TAIL = 4
_MASK = "****"
_NOT_ALNUM = re.compile(r"[^0-9A-Za-z]")


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    doc_title: str
    publisher: str | None
    year: int | None
    page: int
    typologies: tuple[str, ...]
    score: float
    text: str | None = None


def excerpt_typology(requested: list[str], tags: tuple[str, ...]) -> str | None:
    return next((typology for typology in requested if typology in tags), None)


def _mask_bank_key(m: re.Match[str]) -> str:
    acct = _NOT_ALNUM.sub("", m.group(2))
    return f"{m.group(1)}_{_MASK}{acct[-_TAIL:]}" if len(acct) >= _TAIL else m.group(0)


def _mask_hex_run(m: re.Match[str]) -> str:
    joined = _NOT_ALNUM.sub("", m.group(0))
    digits = sum(c.isdigit() for c in joined)
    return _MASK + joined[-_TAIL:] if len(joined) >= _HEX_MIN and digits >= _HEX_DIGITS_MIN else m.group(0)


def _mask_digit_run(m: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", m.group(0))
    return _MASK + digits[-_TAIL:] if len(digits) >= _DIGITS_MIN else m.group(0)


def masked_query(query: str | None) -> str | None:
    """외부 임베딩으로 가기 전 가리기 — NFKC·하이픈 변형 정규화 → 은행 번호 + 나뉜 계좌(`10_****5678`) → 16진 나뉜 계좌
    (구분자 뺀 길이 8 이상·숫자 4개 이상) → 구분자 낀 숫자 8개 이상 → `mask_question`(계좌 키·맨 계좌). 끝 4자리만 남김.
    쉼표 낀 금액은 그대로(쉼표는 구분자 아님) · 8자리 이상 숫자는 금액·날짜여도 가림. 가린 뒤 공백만이면 None."""
    if query is None:
        return None
    text = _HYPHENS.sub("-", unicodedata.normalize("NFKC", query))
    text = _HEX_RUN.sub(_mask_hex_run, _BANK_KEY.sub(_mask_bank_key, text))
    masked = mask_question(_DIGIT_RUN.sub(_mask_digit_run, text))
    return masked if masked.strip() else None


def query_text(typologies: list[str], masked: str | None) -> str:
    chosen = set(typologies)
    patterns = [TYPOLOGY_PATTERN_EN[t] for t in TYPOLOGY_ORDER if t in chosen]
    return " ".join([*patterns, masked] if masked else patterns)


def arrange(hits: list[Hit], *, top_k: int, per_doc: int) -> list[Hit]:
    out: list[Hit] = []
    seen: set[str] = set()
    per: dict[str, int] = {}
    for h in sorted((h for h in hits if h.score >= MIN_SIMILARITY), key=lambda h: (-h.score, h.chunk_id)):
        if h.chunk_id in seen or per.get(h.doc_id, 0) >= per_doc:
            continue
        seen.add(h.chunk_id)
        per[h.doc_id] = per.get(h.doc_id, 0) + 1
        out.append(h)
        if len(out) == top_k:
            break
    return out
