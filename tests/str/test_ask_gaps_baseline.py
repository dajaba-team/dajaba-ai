"""사각지대 측정 세트 기준선 녹화 재생 — 358·359 고치기 전 코드 · ask_plan_v1·ask_answer_v1 (SCRUM-359, 정본 docs/str/08).

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

ITEMS = load_json(judge.GAPS_SET)["items"]

# 08 "결과 — 기준선" 표와 같은 값 (id: 상태, 판정)
BASELINE = {
    "N1": ("NO_DATA", judge.NOT_ANSWERED),
    "N2": ("ANSWERED", judge.RIGHT),
    "T1": ("NO_DATA", judge.NOT_ANSWERED),
    "T2": ("NO_DATA", judge.NOT_ANSWERED),
    "T3": ("NO_DATA", judge.NOT_ANSWERED),
    "V1": ("ANSWERED", judge.WRONG),
    "V2": ("NO_DATA", judge.NOT_ANSWERED),
    "V3": ("NO_DATA", judge.NOT_ANSWERED),
    "X1": ("NO_DATA", judge.NOT_ANSWERED),
    "X2": ("NO_DATA", judge.NOT_ANSWERED),
    "C1": ("ANSWERED", judge.RIGHT),
    "C2": ("ANSWERED", judge.WRONG),
    "O1": ("ANSWERED", judge.RIGHT),
    "O2": ("ANSWERED", judge.RIGHT),
    "O3": ("ANSWERED", judge.RIGHT),
    "O4": ("ANSWERED", judge.RIGHT),
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


def test_baseline_wrong_and_targets() -> None:
    """기준선 틀림 2개 = V1(입금 상대 중 타행 — 방향 없는 자행·타행 수) · C2(지시어 질문에 값으로 답함)."""
    wrong = sorted(i for i, (_s, mark) in BASELINE.items() if mark == judge.WRONG)
    assert wrong == ["C2", "V1"]
    rows = [judge.Row(it, BASELINE[it["id"]][1], 0, BASELINE[it["id"]][0]) for it in ITEMS]
    assert judge.target_lines_gaps(rows)[:3] == [
        "틀림 2/16 (목표 0)",
        "보류 0/16 (목표 2 이하)",
        "ANSWER 맞음 5/5 (목표 5)",
    ]
