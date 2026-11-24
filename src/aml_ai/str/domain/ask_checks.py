"""질문 답변 코드 검사·근거 (docs/str/06 "질문 답변에 도는 코드 검사", SCRUM-290 · SCRUM-362 자리표). 순수 함수.

숫자·금액·날짜·계좌는 코드가 자리표에서 채운다(`ask_slots`) — 답 문장을 해석하는 검사(요약 4종·금액·방향)는 없다.
검사 줄은 `EVIDENCE_IN_SCOPE` 1줄: 아래 순서로 처음 걸린 것의 고정 표시·reason 하나(06 표). 통과해도 1줄.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

from aml_ai.shared.schemas.str import CheckReason, CodeCheck, CodeCheckName, Facts
from aml_ai.shared.schemas.str.ask import ASK_ANSWER_MAX
from aml_ai.shared.text import utf16_len_nfc
from aml_ai.str.domain.ask_bundles import ask_fact_keys
from aml_ai.str.domain.ask_endings import outside_predicates
from aml_ai.str.domain.ask_qualifier import extreme_mismatch, period_mismatch
from aml_ai.str.domain.ask_question import other_case_numbers
from aml_ai.str.domain.ask_slots import AskSlots
from aml_ai.str.domain.constants_ask import (
    ASK_BOTH_DIRECTION_WORDS,
    ASK_CP_BOTH_WORDS,
    ASK_CP_IN_WORDS,
    ASK_CP_OUT_WORDS,
    ASK_EN_IN_WORDS,
    ASK_EN_OUT_WORDS,
    COMPARE_MARK,
    EVIDENCE_OUT_OF_SCOPE_MARK,
    NO_SLOT_MARK,
    OPPOSITE_DIRECTION_MARK,
    OTHER_CASE_MARK,
    OUTSIDE_NUMBER_MARK,
    PREDICATE_MARK,
    QUALIFIER_MARK,
    RE_EXCLUDED_DIRECTION,
    RE_OUTSIDE_COMPARE,
    RE_OUTSIDE_NUMBER,
    SLOT_ERROR_MARK,
    TOO_LONG_MARK,
)
from aml_ai.str.domain.constants_ask_qualifier import RE_DATE_QUALIFIER, RE_EXTREME_QUALIFIER

R = CheckReason
_SIDES = ("inbound", "outbound")


def run(slots: AskSlots, question: str = "", case_no: str = "") -> list[CodeCheck]:
    """EVIDENCE_IN_SCOPE 1줄. 결과 section 은 None."""
    fail = _first_failure(slots, question, case_no)
    return [
        CodeCheck(
            check=CodeCheckName.EVIDENCE_IN_SCOPE,
            section=None,
            draft_value=fail[1] if fail else None,
            source_value=None,
            match=fail is None,
            reason=fail[0] if fail else None,
        )
    ]


def _first_failure(slots: AskSlots, question: str, case_no: str) -> tuple[CheckReason, str] | None:
    """06 표 순서: 범위 밖 → 자리표 오류 → 다른 케이스 → 자리표 밖 숫자 → 비교 → 서술어 → 반대 방향 → 한정어 → 자리표 없음 → 길이."""
    outside = unicodedata.normalize("NFKC", slots.outside)
    others = other_case_numbers(outside, case_no) if case_no else []
    numbers = RE_OUTSIDE_NUMBER.findall(outside)
    opposite = opposite_direction_keys(slots, question)
    if slots.out_of_scope:
        return R.OUT_OF_SCOPE, EVIDENCE_OUT_OF_SCOPE_MARK.format(n=slots.out_of_scope)
    if slots.errors:
        return R.UNPARSED, SLOT_ERROR_MARK.format(n=slots.errors)
    if others:
        return R.OUT_OF_SCOPE, OTHER_CASE_MARK.format(n=len(others))
    if numbers:
        return R.UNPARSED, OUTSIDE_NUMBER_MARK.format(n=len(numbers))
    if compares := RE_OUTSIDE_COMPARE.findall(outside):  # 원칙 (B) — 비교는 compare 자리표로(B1)
        return R.UNPARSED, COMPARE_MARK.format(n=len(compares))
    if bad := outside_predicates(slots.marked):  # 허용 목록 밖 끝맺음·수량(추가 검토 3)
        return R.UNPARSED, PREDICATE_MARK.format(n=bad)
    if opposite:
        return R.MISMATCH, OPPOSITE_DIRECTION_MARK.format(n=opposite)
    if off := qualifier_mismatch(slots, question):  # 질문 한정어 ↔ 집계 범위(추가 검토 3 H2)
        return R.MISMATCH, QUALIFIER_MARK.format(n=off)
    if not slots.keys:
        return R.MISSING, NO_SLOT_MARK
    if utf16_len_nfc(slots.text) > ASK_ANSWER_MAX:
        return R.UNPARSED, TOO_LONG_MARK
    return None


def qualifier_mismatch(slots: AskSlots, question: str) -> int:
    """질문 기간·최대/최소 한정어와 자리표 집계 범위가 다른 수(06). facts 는 기간 전체 집계 — 일별·방향별 최대 없음.

    기간 조건과 극값 조건을 따로 세서 더함(★B8 D-1). 기간 예외는 자리표 출현마다(★B8 D-2).
    """
    q = unicodedata.normalize("NFKC", question)
    period = period_mismatch(slots, asked=RE_DATE_QUALIFIER.search(q) is not None)
    side = question_side(question)
    return period + (
        extreme_mismatch(slots, side) if RE_EXTREME_QUALIFIER.search(q) and side in _SIDES else 0
    )


def question_side(question: str) -> str | None:
    """질문 방향 — "inbound"·"outbound"·"both"(입출금을 함께 물음)·None(방향 낱말 없음). NFKC·소문자.

    `말고`·`제외하고`·`빼고`·`외에` 바로 앞 방향 낱말은 배제한 방향이라 지움(추가 검토 2 H4). 영어 낱말도 봄.
    """
    q = unicodedata.normalize("NFKC", question).casefold()
    q = RE_EXCLUDED_DIRECTION.sub(" ", q)
    both = any(w in q for w in ASK_BOTH_DIRECTION_WORDS)
    for word in sorted(ASK_CP_BOTH_WORDS, key=len, reverse=True):
        q = q.replace(word, " ")
    has_in = _has(q, (*ASK_CP_IN_WORDS, *ASK_EN_IN_WORDS))
    has_out = _has(q, (*ASK_CP_OUT_WORDS, *ASK_EN_OUT_WORDS))
    if both or (has_in and has_out):
        return "both"
    if has_in != has_out:
        return "inbound" if has_in else "outbound"
    return None


def opposite_direction_keys(slots: AskSlots, question: str) -> int:
    """방향 + 지표 어긋난 자리표 수(06 3번 — (A) 애매하면 막는다, 키 이름만 봄).

    지표 = 방향만 뺀 키 나머지(은행 구분·통화 보존). 한 방향 질문: 반대 방향 키는 같은 지표의 질문 방향 키가 있어야 함 —
    예외는 **정정 절**: 질문 방향 0건 건수 키가 그 키보다 앞에 있고, 그 키의 문장(LLM 글)에 질문 방향 낱말이 없을 때.
    양방향 질문: 쓴 방향 키마다 같은 지표의 다른 방향 키가 있어야 함.
    """
    side = question_side(question)
    if side is None:
        return 0
    used = {_side_metric(k) for k in slots.keys}
    bad = 0
    for key, pos, sentence in slots.spans:
        s, metric = _side_metric(key)
        if s is None:
            continue
        if side == "both":
            bad += (_other(s), metric) not in used
        elif s != side and (side, metric) not in used and not _corrected(slots, side, pos, sentence):
            bad += 1
    return bad


def _corrected(slots: AskSlots, side: str, pos: int, sentence: str) -> bool:
    zero_before = any(
        k in slots.zero_keys and _side_metric(k)[0] == side and p < pos for k, p, _ in slots.spans
    )
    words = (
        (*ASK_CP_IN_WORDS, *ASK_EN_IN_WORDS) if side == "inbound" else (*ASK_CP_OUT_WORDS, *ASK_EN_OUT_WORDS)
    )
    return zero_before and not _has(unicodedata.normalize("NFKC", sentence).casefold(), words)


def _has(text: str, words: Sequence[str]) -> bool:
    return any(w in text for w in words)


def _other(side: str) -> str:
    return "outbound" if side == "inbound" else "inbound"


def _side_metric(key: str) -> tuple[str | None, str | None]:
    """(방향, 지표) — 지표는 방향만 뺀 나머지 그대로(`amount.USD`·`cp.other_bank_accounts`). 방향 없는 키는 (None, None)."""
    parts = key.split(".")
    if parts[0] in _SIDES:
        return parts[0], ".".join(parts[1:])
    if parts[0] == "counterparties_by_direction" and len(parts) == 3 and parts[1] in _SIDES:
        return parts[1], "cp." + parts[2]
    return None, None


def cited_evidence_ids(facts: Facts, keys: Sequence[str]) -> list[int]:
    """자리표 키 → 거래 ID 합집합(질문 답변 인용 키 `ask_fact_keys`). 거래 없는 키는 기여 0."""
    table = ask_fact_keys(facts)
    return sorted({i for k in keys if k in table for i in table[k]})
