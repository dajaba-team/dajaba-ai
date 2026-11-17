"""SCRUM-265 (2/2) — 뒷받침 안 됨일 때 금지 낱말 검사(낱말 단위) 공용 (docs/str/05 "유형 뒷받침 판정")."""

from __future__ import annotations

import re

from aml_ai.str.domain.constants_v4 import UNSUPPORTED_BANNED_WORDS

# 낱말 단위 — 앞이 한글이면 다른 낱말의 일부(`불충족` 안의 `충족`). `뒷받침하는` 은 목록에 없음.
_RE_BANNED = re.compile(r"(?<![가-힣])(?:" + "|".join(map(re.escape, UNSUPPORTED_BANNED_WORDS)) + ")")


def banned_hits(text: str) -> list[str]:
    return _RE_BANNED.findall(text)
