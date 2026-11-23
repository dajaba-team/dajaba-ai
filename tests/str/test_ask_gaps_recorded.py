"""사각지대 측정 세트 녹화 재생 — ask_plan_v1·ask_answer_v6 자리표 (SCRUM-359 세트 · SCRUM-362, 정본 docs/str/08).

목표 (A) 엄격(08, 결과 보기 전 2026-11-22 고정): 틀림 0/16 · 보류 2 이하 · ANSWER 맞음 5/5. 답 문장은 비교하지 않고
상태·판정만 본다(틀림 규칙은 이름표 뺀 LLM 글, SCRUM-362 ★B3-5). v2·v3 표는 08 · v2·v3 녹화에 남음.
"""

from __future__ import annotations

import pytest
from tools import ask_premise_judge as judge

from tests.conftest import load_json
from tests.str.ask_recorded_support import replay_verdict

ITEMS = load_json(judge.GAPS_SET)["items"]

_NO = ("NO_DATA", judge.NOT_ANSWERED)
_OK = ("ANSWERED", judge.RIGHT)
# 08 "결과 — v6 녹화" 표와 같은 값 (id: 상태, 판정) — X1 은 `--only X1` 로 저장(계획 다름 뒤)
V6 = {
    "N1": _NO,
    "N2": _OK,
    "T1": _NO,
    "T2": _NO,
    "T3": _NO,
    "V1": _OK,
    "V2": _NO,
    "V3": _NO,
    "X1": _NO,
    "X2": _NO,
    "C1": _OK,
    "C2": ("OUT_OF_SCOPE", judge.OTHER),
    "O1": _OK,
    "O2": _OK,
    "O3": _OK,
    "O4": _OK,
}


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


@pytest.mark.parametrize("it", ITEMS, ids=lambda i: i["id"])
def test_v6_replay_matches_table(it: dict) -> None:
    assert replay_verdict(it) == V6[it["id"]]


def test_v6_targets() -> None:
    rows = [judge.Row(it, mark, 0, status) for it in ITEMS for status, mark in [replay_verdict(it)]]
    assert judge.target_lines_gaps(rows)[:4] == [
        "틀림 0/16 (목표 0)",
        "보류 0/16 (목표 2 이하)",
        "ANSWER 맞음 5/5 (목표 5)",
        "통과 16/16 (참고)",
    ]


def test_c2_follow_up_out_of_scope_by_code() -> None:
    """이어지는 질문(04) — 계획·답 호출 없이 OUT_OF_SCOPE · BLOCK 통과."""
    it = next(i for i in ITEMS if i["id"] == "C2")
    status, mark = replay_verdict(it)
    assert (status, mark) == ("OUT_OF_SCOPE", judge.OTHER) and judge.passed(it, mark, status)


def test_o1_comparison_uses_compare_slots() -> None:
    """08 (B1) 목표 — O1(`입금이 출금보다 많아?`) 답이 compare 자리표를 씀(비교는 코드가 렌더링)."""
    from tests.str.ask_recorded_support import facts_for, recorded
    from tests.str.ask_service_support import ask_request, build_service

    it = next(i for i in ITEMS if i["id"] == "O1")
    svc, _ = build_service(recorded(), facts=facts_for(it))
    res = svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))
    assert res.status.value == "ANSWERED" and any(c.startswith("compare.") for c in res.cites)
