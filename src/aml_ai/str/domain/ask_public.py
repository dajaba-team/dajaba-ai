"""질문 답변 응답에 싣는 검사 줄 — draft_value 허용 모양 (docs/str/06 "질문 답변" 7번, SCRUM-290 추가 검토 2). 순수 함수.

검사기가 잘라 낸 조각이라도 모델이 쓴 글자가 섞일 수 있다(AMOUNT 안전망 한글 낱말·한글 수사).
응답에는 숫자·날짜·통화·계좌 모양 토큰과 고정 표시만 싣고, 그 밖은 `MASK` — 원문은 저장 행 `llm_answer` 에만.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from aml_ai.shared.schemas.str import CodeCheck
from aml_ai.str.domain.constants import BANK_COUNT_UNITS, COUNT_UNITS_COUNT, COUNT_UNITS_SMALL, PATH_HOP_UNITS
from aml_ai.str.domain.constants_ask import (
    COMPARE_MARK,
    EVIDENCE_OUT_OF_SCOPE_MARK,
    NO_SLOT_MARK,
    OPPOSITE_DIRECTION_MARK,
    OTHER_CASE_MARK,
    OUTSIDE_NUMBER_MARK,
    PREDICATE_MARK,
    QUALIFIER_MARK,
    SLOT_ERROR_MARK,
    TOO_LONG_MARK,
)

MASK = "답 조각 가림"
_SLOT_MARKS = (
    SLOT_ERROR_MARK,
    OUTSIDE_NUMBER_MARK,
    COMPARE_MARK,
    PREDICATE_MARK,
    OPPOSITE_DIRECTION_MARK,
    QUALIFIER_MARK,
    NO_SLOT_MARK,
    TOO_LONG_MARK,
)

_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_UNITS = "|".join(dict.fromkeys((*COUNT_UNITS_SMALL, *COUNT_UNITS_COUNT, *BANK_COUNT_UNITS, *PATH_HOP_UNITS)))
_DATE = r"(?:\d{4}-\d{2}-\d{2}|\d{4}년 ?\d{1,2}월 ?\d{1,2}일|\d{1,2}월 ?\d{1,2}일|\d{4}/\d{1,2}/\d{1,2}|\d{4}\.\d{1,2}\.\d{1,2})"
_TIME = r"(?:[T ]\d{1,2}:\d{2}(?::\d{2})?| (?:(?:오전|오후) )?\d{1,2}시(?: \d{1,2}분)?)"
_ALLOWED = re.compile(
    "|".join(
        (
            rf"{_NUM} ?(?:{_UNITS})",  # 건수
            rf"{_NUM} \([A-Z]{{3}}\)",  # 금액 (통화)
            rf"{_DATE}{_TIME}?",  # 날짜(+시각)
            r"\d{1,4}_[0-9A-Z*]{4,}|\*{4}[0-9A-Z]{4}|끝자리 ?[0-9A-Z]{4}",  # 계좌 모양
            re.escape(EVIDENCE_OUT_OF_SCOPE_MARK).replace(r"\{n\}", r"\d+"),  # 고정 표시
            re.escape(OTHER_CASE_MARK).replace(r"\{n\}", r"\d+"),  # 고정 표시(추가 검토 4 H6)
            *(re.escape(m).replace(r"\{n\}", r"\d+") for m in _SLOT_MARKS),  # 자리표 표시(SCRUM-362)
        )
    )
)


def public_checks(checks: Sequence[CodeCheck]) -> list[CodeCheck]:
    """draft_value 가 허용 모양 전체 일치가 아니면 MASK. 다른 칸(source_value·match·reason)은 그대로."""
    return [c if _allowed(c.draft_value) else c.model_copy(update={"draft_value": MASK}) for c in checks]


def _allowed(value: str | None) -> bool:
    return value is None or _ALLOWED.fullmatch(value) is not None
