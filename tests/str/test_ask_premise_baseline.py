"""전제·방향 평가 세트 기준선 녹화 재생 — 지금 develop 코드 · ask_plan_v1·ask_answer_v1 (SCRUM-358, 정본 docs/str/08).

기준선은 고치기 전 결과를 그대로 남기는 것 — 목표(틀림 0)에 못 미친 값이 기대값이다. 답 문장은 비교하지 않고
상태·판정만 본다(판정 `tools/ask_premise_judge.py`).
"""

from __future__ import annotations

import pytest
from tools import ask_premise_judge as judge

from aml_ai.shared.schemas.str import Facts
from tests.conftest import FIXTURES, load_json
from tests.str.ask_recorded_support import recorded
from tests.str.ask_service_support import ask_request, build_service

ITEMS = load_json(judge.PREMISE_SET)["items"]

# 08 "결과 — 기준선" 표와 같은 값 (id: 상태, 판정)
BASELINE = {
    "P1": ("ANSWERED", judge.WRONG),
    "P2": ("ANSWERED", judge.RIGHT),
    "P3": ("ANSWERED", judge.WRONG),
    "P4": ("ANSWERED", judge.RIGHT),
    "P5": ("NO_DATA", judge.NOT_ANSWERED),
    "P6": ("NO_DATA", judge.NOT_ANSWERED),
    "D1": ("ANSWERED", judge.RIGHT),
    "D2": ("ANSWERED", judge.RIGHT),
    "D3": ("ANSWERED", judge.WRONG),
    "D4": ("ANSWERED", judge.WRONG),
    "D5": ("ANSWERED", judge.RIGHT),
}


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _replay(it: dict) -> tuple[str, str]:
    facts = Facts.model_validate(load_json(FIXTURES / f"facts_{it['facts_case']}.json"))
    svc, repo = build_service(recorded(), facts=facts)
    res = svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))
    answer = (repo.saved[0]["response_payload"].get("llm_answer") or {}).get("answer")
    return res.status.value, judge.verdict(it, res.status.value, answer)


@pytest.mark.parametrize("it", ITEMS, ids=lambda i: i["id"])
def test_baseline_replay_matches_table(it: dict) -> None:
    assert _replay(it) == BASELINE[it["id"]]


def test_baseline_wrong_are_counterparty_direction_questions() -> None:
    """기준선 틀림 4개 = 방향 붙은 상대 수 질문(유입 0 의 입금 상대 · 유출 0 의 출금 상대 · 양방향 둘)."""
    wrong = sorted(i for i, (_s, mark) in BASELINE.items() if mark == judge.WRONG)
    assert wrong == ["D3", "D4", "P1", "P3"]
