"""추가 검토 1(SCRUM-362) 반례 — 판정(자리표 키 보존) · v1·v2 계획 명시 비교. 고치기 전에 먼저 넣어 실패를 확인함.

4 판정 · 7 v1·v2 계획 녹화(정본 docs/str/08). LLM 없음. 답 경로 반례는 `test_ask_review_362_1.py`.
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


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


# ---------- 4 판정 — 자리표 키(방향·지표) 보존 ----------

GAPS = {i["id"]: i for i in load_json(judge.GAPS_SET)["items"]}
PREMISE = {i["id"]: i for i in load_json(judge.PREMISE_SET)["items"]}


def _verdict(it: dict, raw: str) -> str:
    svc, repo = build_service(FixedAnswer(recorded(), raw), facts=facts_for(it))
    res = svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))
    piece = extract(facts_for(it), it["rule_id"], res.generation_meta.bundles, LABELS)
    written = ask_judge_text.judge_text(raw, piece, LABELS)
    conflict = ask_judge_text.slot_direction_conflicts(raw, piece) > 0
    return judge.verdict(
        it, res.status.value, res.answer, written, conflict, ask_judge_text.slot_direction_unclear(raw, piece)
    )


def test_v3_outbound_claim_with_both_direction_wire_count_is_wrong() -> None:
    raw = "출금은 {{payment_format_counts.Wire|이에요}}. 개별 거래 시각은 확인할 수 없어요."
    assert _verdict(GAPS["V3"], raw) == judge.WRONG


def test_p4_correction_then_values_stays_right() -> None:
    raw = "질문하신 출금 방향의 거래는 없어요. 이 케이스에는 {{outbound.count|이}} 확인되며, {{inbound.amount.USD|이}} 확인돼요."
    assert _verdict(PREMISE["P4"], raw) == judge.RIGHT


# 7 v1·v2 계획 녹화 비교(추가 검토 1 M3)는 ★C 에 지움 — ask_plan_v2 녹화를 PR 에서 빼 리포 밖 운영 폴더에 보관. 결과는 08 "계획 흔들림 재기"
