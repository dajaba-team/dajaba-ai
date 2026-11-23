"""추가 검토 2(SCRUM-362) 반례 — 판정 도구. V3·P4 최종 판정 고정 (정본 docs/str/08). LLM 없음.

판정은 서비스 검사와 코드를 나누지 않고 독립 — 자리표와 같은 절의 앞·뒤 방향 낱말을 대조, `없고`·`대신`·`고,` 같은 절
전환에서 끊고, 한 절에 두 방향 낱말이 섞여 불명확하면 보류.
"""

from __future__ import annotations

import pytest
from tools import ask_judge_text
from tools import ask_premise_judge as judge

from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import load_json
from tests.str.ask_recorded_support import FixedAnswer, facts_for, recorded
from tests.str.ask_service_support import ask_request, build_service

LABELS = load_display_labels()
GAPS = {i["id"]: i for i in load_json(judge.GAPS_SET)["items"]}
PREMISE = {i["id"]: i for i in load_json(judge.PREMISE_SET)["items"]}


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _verdict(it: dict, raw: str) -> str:
    svc, _ = build_service(FixedAnswer(recorded(), raw), facts=facts_for(it))
    res = svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))
    piece = extract(facts_for(it), it["rule_id"], res.generation_meta.bundles, LABELS)
    written = ask_judge_text.judge_text(raw, piece, LABELS)
    conflict = ask_judge_text.slot_direction_conflicts(raw, piece) > 0
    unclear = ask_judge_text.slot_direction_unclear(raw, piece)
    return judge.verdict(it, res.status.value, res.answer, written, conflict, unclear)


def test_v3_direction_word_after_slot_is_wrong() -> None:
    """V3 — 전체 Wire 2건(모두 입금)을 "모두 출금" 이라 함: 자리표 뒤 서술어의 방향."""
    raw = "{{payment_format_counts.Wire|은}} 모두 출금이에요. 개별 거래 시각은 확인할 수 없어요."
    assert _verdict(GAPS["V3"], raw) == judge.WRONG


def test_p4_clause_transition_breaks_direction_link() -> None:
    """P4 — `출금은 0건이고, 대신 입금 합계` : 앞 절의 `출금` 이 다음 절 입금 자리표로 넘어가지 않음 → 맞음."""
    raw = "출금은 {{outbound.count}}이고, 대신 {{inbound.amount.USD|이}} 확인돼요."
    assert _verdict(PREMISE["P4"], raw) == judge.RIGHT


def test_both_directions_in_one_clause_is_hold() -> None:
    """한 절에 입금·출금 낱말 — 연결 불명확이면 보류(판정 함수 직접 — 이 꼴은 서비스가 먼저 막기도 함)."""
    it = PREMISE["P4"]
    piece = extract(facts_for(it), it["rule_id"], ["flows"], LABELS)
    raw = "{{outbound.count|이에요}}. 입금과 달리 출금은 {{inbound.amount.USD|이에요}}."
    assert ask_judge_text.slot_direction_unclear(raw, piece)
    assert judge.verdict(it, "ANSWERED", "렌더링 글", "값 글", conflict=False, unclear=True) == judge.HOLD
