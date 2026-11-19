"""질문 속 계좌 가리기 — LLM 에 가는 질문 복사본만. 저장·응답은 원문 (docs/str/04 "질문 속 계좌", SCRUM-290). 순수 함수."""

from __future__ import annotations

import re
import unicodedata

from aml_ai.str.domain.constants_ask import (
    ACCOUNT_MASK,
    RE_ASK_ACCOUNT_BARE,
    RE_ASK_ACCOUNT_FULL,
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
