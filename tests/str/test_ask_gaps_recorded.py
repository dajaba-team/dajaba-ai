"""사각지대 측정 세트 녹화 재생 — 358·359 고친 코드 · ask_plan_v1·ask_answer_v2 (SCRUM-359, 정본 docs/str/08).

목표 (A) 엄격(08, 결과 보기 전 2026-11-22 고정): 틀림 0/16 · 보류 2 이하 · ANSWER 맞음 5/5. 답 문장은 비교하지 않고
상태·판정만 본다. 고치기 전 기준선(틀림 2/16 — V1·C2)은 08 표 · 기준선 커밋 `67d8da7`.
"""

from __future__ import annotations

import pytest
from tools import ask_premise_judge as judge

from tests.conftest import load_json
from tests.str.ask_recorded_support import facts_for, recorded
from tests.str.ask_service_support import ask_request, build_service

ITEMS = load_json(judge.GAPS_SET)["items"]

# 08 "결과 — 고친 뒤" 표와 같은 값 (id: 상태, 판정)
V2 = {
    "N1": ("NO_DATA", judge.NOT_ANSWERED),
    "N2": ("ANSWERED", judge.RIGHT),
    "T1": ("NO_DATA", judge.NOT_ANSWERED),
    "T2": ("NO_DATA", judge.NOT_ANSWERED),
    "T3": ("NO_DATA", judge.NOT_ANSWERED),
    "V1": ("ANSWERED", judge.RIGHT),
    "V2": ("NO_DATA", judge.NOT_ANSWERED),
    "V3": ("NO_DATA", judge.NOT_ANSWERED),
    "X1": ("NO_DATA", judge.NOT_ANSWERED),
    "X2": ("NO_DATA", judge.NOT_ANSWERED),
    "C1": ("ANSWERED", judge.RIGHT),
    "C2": ("OUT_OF_SCOPE", judge.OTHER),
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
    svc, repo = build_service(recorded(), facts=facts_for(it))
    res = svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))
    answer = (repo.saved[0]["response_payload"].get("llm_answer") or {}).get("answer")
    return res.status.value, judge.verdict(it, res.status.value, answer)


@pytest.mark.parametrize("it", ITEMS, ids=lambda i: i["id"])
def test_v2_replay_matches_table(it: dict) -> None:
    assert _replay(it) == V2[it["id"]]


def test_v2_targets() -> None:
    """08 목표 (A) — 기준선 틀림 V1(방향별 자행·타행)·C2(이어지는 질문)이 고친 뒤 통과."""
    rows = [judge.Row(it, mark, 0, status) for it in ITEMS for status, mark in [_replay(it)]]
    assert judge.target_lines_gaps(rows)[:4] == [
        "틀림 0/16 (목표 0)",
        "보류 0/16 (목표 2 이하)",
        "ANSWER 맞음 5/5 (목표 5)",
        "통과 16/16 (참고)",
    ]


def test_c2_follow_up_out_of_scope_by_code() -> None:
    """이어지는 질문(04) — 계획·답 호출 없이 OUT_OF_SCOPE · BLOCK 통과."""
    it = next(i for i in ITEMS if i["id"] == "C2")
    status, mark = _replay(it)
    assert (status, mark) == ("OUT_OF_SCOPE", judge.OTHER) and judge.passed(it, mark, status)
