"""배포용 본문과 양쪽에 같은 방식으로 적용하는 자동 지표."""

from __future__ import annotations

import re
from typing import Any

from aml_ai.shared.schemas.str import Facts, NarrativeSection, SectionV2
from tests.str.v4_slot_support import failures

SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n+")


def side_metrics(facts: Facts, sections: list[NarrativeSection]) -> dict[str, Any]:
    """문장 부호 뒤 공백 또는 줄바꿈으로 나누며, 소수점·날짜 내부는 나누지 않는다."""
    return {
        "code_check_failures": len(failures(facts, sections)),
        "chars": sum(len(s.text) for s in sections),
        "sentences": {
            s.section.value: sum(bool(part.strip()) for part in SENTENCE_BREAK.split(s.text))
            for s in sections
        },
    }


def pair_md(
    number: int,
    group: str | None,
    a: list[NarrativeSection],
    b: list[NarrativeSection],
) -> str:
    """쌍 번호와 고객 묶음만 표시하고 양쪽 섹션을 같은 순서로 놓는다."""
    lines = [f"## 쌍 {number}", ""]
    if group:
        lines.extend([f"같은 고객 묶음 {group.removeprefix('g')}", ""])
    for side, sections in (("A", a), ("B", b)):
        lines.extend([f"### {side}", ""])
        by_section = {s.section: s.text for s in sections}
        for section in SectionV2:
            lines.extend([f"#### {section.value}", "", by_section[section], ""])
    lines.extend(
        [
            "선택 A/B/차이 없음: __",
            "",
            "그대로 쓰려면 고칠 문장 수 A __ / B __",
            "",
            "틀린 문장 원문 A __ / B __",
            "",
            "한 줄 이유: __",
            "",
        ]
    )
    return "\n".join(lines)
