"""질문 속 계좌 가리기 · 이어지는 질문 (docs/str/04 "질문 속 계좌"·"이어지는 질문", SCRUM-290·359). 순수 함수.

가리기는 LLM 에 가는 질문 복사본만 — 저장·응답은 원문.
"""

from __future__ import annotations

import re
import unicodedata

from aml_ai.str.domain.constants_ask import (
    ACCOUNT_MASK,
    ASK_FOLLOW_UP_JOIN_HEADS,
    ASK_FOLLOW_UP_MAX_CHARS,
    ASK_FOLLOW_UP_SET_HEADS,
    ASK_TOPIC_WORDS,
    RE_ASK_ACCOUNT_BARE,
    RE_ASK_ACCOUNT_FULL,
    RE_ASK_COUNT_TOPIC,
    RE_CASE_NO,
)
from aml_ai.str.domain.masking import ACCOUNT_TAIL, mask_account_key


def mask_question(text: str) -> str:
    """NFKC(전각 → ASCII) 뒤 은행 번호 붙은 계좌 키 → `10_****BD30`, 맨 계좌 → `****BD30`.

    돌려주는 값은 LLM 복사본(NFKC 됨). 격리(`<`·`>`)는 그 다음 `ask_llm.render_plan_user` 에서.
    """
    normalized = unicodedata.normalize("NFKC", text)
    masked = RE_ASK_ACCOUNT_FULL.sub(lambda m: mask_account_key(m.group(0)), normalized)
    return RE_ASK_ACCOUNT_BARE.sub(_mask_bare, masked)


def _mask_bare(m: re.Match[str]) -> str:
    return ACCOUNT_MASK + m.group(0)[-ACCOUNT_TAIL:]


def is_follow_up(text: str) -> bool:
    """앞 답을 가리키는 짧은 질문(04) — 20자 이하 + ① `그중`·`그 다음`·`거기서` 로 시작하면 늘, ② `그럼`·`그러면` 으로
    시작하면 그 말을 뗀 나머지가 ①이거나, 주제 낱말·숫자+건이 없을 때(추가 검토 1·2 M3·M2)."""
    q = unicodedata.normalize("NFKC", text).strip()
    if len(q) > ASK_FOLLOW_UP_MAX_CHARS:
        return False
    if q.startswith(ASK_FOLLOW_UP_SET_HEADS):
        return True
    join = next((h for h in ASK_FOLLOW_UP_JOIN_HEADS if q.startswith(h)), None)
    if join is None:
        return False
    rest = q[len(join) :].strip()
    if rest.startswith(ASK_FOLLOW_UP_SET_HEADS):
        return True
    if RE_ASK_COUNT_TOPIC.search(rest):
        return False
    return not any(w in rest for w in ASK_TOPIC_WORDS)


def other_case_numbers(text: str, case_no: str) -> list[str]:
    """글에 나온 케이스 번호 중 이 요청의 case_no 가 아닌 것(추가 검토 4 H6)."""
    return [m for m in RE_CASE_NO.findall(unicodedata.normalize("NFKC", text)) if m != case_no]


def blocked_before_plan(question: str, case_no: str) -> bool:
    """계획 LLM 전에 코드가 범위 밖으로 끝낼 질문 — 이어지는 질문 · 다른 케이스 번호(04)."""
    return is_follow_up(question) or bool(other_case_numbers(question, case_no))
