"""전제·방향 평가 세트 녹화 재생 — ask_plan_v1·ask_answer_v6 자리표 (SCRUM-358 세트 · SCRUM-362, 정본 docs/str/08).

목표(08, 결과 보기 전 2026-11-22 고정): 틀림 0/11 · 전제 틀림 보류 0/6 · 방향 질문 맞음 5/5. 답 문장은 비교하지 않고
상태·판정만 본다(판정 `tools/ask_premise_judge.py` — 틀림 규칙은 이름표 뺀 LLM 글, SCRUM-362 ★B3-5).
v2 표(11개 ANSWERED·맞음)·v3 표(보류 2/6)는 08 · v2·v3 녹화에 남음.
"""

from __future__ import annotations

import pytest
from tools import ask_premise_judge as judge

from tests.conftest import load_json
from tests.str.ask_recorded_support import replay_verdict

ITEMS = load_json(judge.PREMISE_SET)["items"]

# 08 "결과 — v6 녹화" 표와 같은 값 (id: 상태, 판정) — 11개 모두 ANSWERED·맞음(P4 는 판정 규칙 고친 뒤 — 옛 규칙 보류)
V6 = {i["id"]: ("ANSWERED", judge.RIGHT) for i in ITEMS}


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


@pytest.mark.parametrize("it", ITEMS, ids=lambda i: i["id"])
def test_v6_replay_matches_table(it: dict) -> None:
    assert replay_verdict(it) == V6[it["id"]]


def test_v6_targets() -> None:
    """08 목표 넷 — 지연은 실제 호출 표(08)에서만."""
    rows = [judge.Row(it, mark, 0, status) for it in ITEMS for status, mark in [replay_verdict(it)]]
    assert judge.target_lines(rows)[:4] == [
        "틀림 0/11 (목표 0)",
        "전제 틀림 보류 0/6 (목표 0)",
        "전제 틀림 통과 6/6 (참고)",
        "방향 질문 맞음 5/5 (목표 5)",
    ]
