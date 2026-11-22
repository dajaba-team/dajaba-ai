"""전제·방향 평가 세트 녹화 재생 — 358·359 고친 코드 · ask_plan_v1·ask_answer_v2 (SCRUM-358, 정본 docs/str/08).

목표(08, 결과 보기 전 2026-11-22 고정): 틀림 0/11 · 전제 틀림 보류 0/6 · 방향 질문 맞음 5/5. 답 문장은 비교하지 않고
상태·판정만 본다(판정 `tools/ask_premise_judge.py`). 고치기 전 기준선(틀림 4/11)은 08 표 · 기준선 커밋 `ad33897`.
"""

from __future__ import annotations

import pytest
from tools import ask_premise_judge as judge

from tests.conftest import load_json
from tests.str.ask_recorded_support import facts_for, recorded
from tests.str.ask_service_support import ask_request, build_service

ITEMS = load_json(judge.PREMISE_SET)["items"]

# 08 "결과 — 고친 뒤" 표와 같은 값 (id: 상태, 판정) — 11개 모두 ANSWERED·맞음
V2 = {i["id"]: ("ANSWERED", judge.RIGHT) for i in ITEMS}


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _replay(it: dict) -> tuple[str, str]:
    svc, repo = build_service(recorded(), facts=facts_for(it))
    res = svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))
    answer = (repo.saved[0]["response_payload"].get("llm_answer") or {}).get("answer")
    return res.status.value, judge.verdict(it, res.status.value, answer)


@pytest.mark.parametrize("it", ITEMS, ids=lambda i: i["id"])
def test_v2_replay_matches_table(it: dict) -> None:
    assert _replay(it) == V2[it["id"]]


def test_v2_targets() -> None:
    """08 목표 넷 — 지연은 실제 호출 표(08)에서만."""
    rows = [judge.Row(it, mark, 0, status) for it in ITEMS for status, mark in [_replay(it)]]
    assert judge.target_lines(rows)[:4] == [
        "틀림 0/11 (목표 0)",
        "전제 틀림 보류 0/6 (목표 0)",
        "전제 틀림 통과 6/6 (참고)",
        "방향 질문 맞음 5/5 (목표 5)",
    ]
