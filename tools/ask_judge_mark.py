"""질문 답변 판정 낱말 한 곳 — 녹화 도구·재생 테스트가 같은 함수 (SCRUM-362, docs/str/08).

복합 WHY 는 묶음별 자리표, 그 밖은 정규식 판정(맞음 = 렌더링 · 틀림 = 이름표 뺀 글 + 같은 절 방향 어긋남 + 비교 대소).
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import AskResponse
from aml_ai.str.domain.ask_bundles import AskPiece
from aml_ai.str.domain.display_labels_check import Labels
from tools import ask_premise_judge as judge
from tools.ask_judge_text import (
    comparison_wrong,
    judge_text,
    slot_direction_conflicts,
    slot_direction_unclear,
)


def mark(item: dict, out: AskResponse, raw: str, piece: AskPiece, labels: Labels) -> str:
    if "expected" in item:
        return judge.compound_mark(item, out.status.value, list(out.cites))
    written = judge_text(raw, piece, labels)
    conflict = slot_direction_conflicts(raw, piece) > 0 or comparison_wrong(raw, piece)
    return judge.verdict(
        item, out.status.value, out.answer, written, conflict, slot_direction_unclear(raw, piece)
    )
