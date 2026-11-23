"""판정 정규식 미리 보기 — 맞는 키로 쓴 v3 답이 이름표를 붙여도 판정에서 맞음인지 (SCRUM-362, 정본 docs/str/08).

결과 보기 전 확인: 계획은 녹화 재생(`ask_plan_v1`), 답은 `fixtures/ask_v3_preview.json` 의 고정 원문(실제 LLM 아님).
판정 규칙·문항·목표는 세트 파일 그대로 — 여기서 안 맞으면 멈추고 보고(08).
"""

from __future__ import annotations

import pytest
from tools import ask_premise_judge as judge
from tools.ask_judge_text import judge_text, slot_direction_conflicts, slot_direction_unclear

from aml_ai.shared.schemas.str import AskStatus
from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json
from tests.str.ask_recorded_support import IN_SCOPE, FixedAnswer, facts_for, recorded, replay_verdict
from tests.str.ask_service_support import ask_request, build_service

ANSWERS = load_json(FIXTURES / "ask_v3_preview.json")["answers"]
PREMISE = load_json(judge.PREMISE_SET)["items"]
GAPS = load_json(judge.GAPS_SET)["items"]


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _run(it: dict):
    svc, _ = build_service(FixedAnswer(recorded(), ANSWERS.get(it["id"])), facts=facts_for(it))
    return svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))


def _verdict(it: dict) -> tuple[str, str]:
    return replay_verdict(it, FixedAnswer(recorded(), ANSWERS.get(it["id"])))


def _rows(items: list[dict]) -> list:
    return [judge.Row(it, mark, 0, status) for it in items for status, mark in [_verdict(it)]]


@pytest.mark.parametrize("it", IN_SCOPE, ids=lambda i: i["id"])
def test_eighteen_set_right_key_answer_is_answered(it: dict) -> None:
    res = _run(it)
    assert res.status is AskStatus.ANSWERED, res.code_checks
    assert "{{" not in res.answer and res.cites


@pytest.mark.parametrize("it", PREMISE, ids=lambda i: i["id"])
def test_premise_right_key_answer_judged_right(it: dict) -> None:
    assert _verdict(it) == ("ANSWERED", judge.RIGHT)


def test_premise_targets_with_right_key_answers() -> None:
    assert judge.target_lines(_rows(PREMISE))[:4] == [
        "틀림 0/11 (목표 0)",
        "전제 틀림 보류 0/6 (목표 0)",
        "전제 틀림 통과 6/6 (참고)",
        "방향 질문 맞음 5/5 (목표 5)",
    ]


@pytest.mark.parametrize("it", [i for i in GAPS if ANSWERS.get(i["id"])], ids=lambda i: i["id"])
def test_gaps_right_key_answer_judged_right(it: dict) -> None:
    assert _verdict(it) == ("ANSWERED", judge.RIGHT)


def test_gaps_targets_with_right_key_answers() -> None:
    assert judge.target_lines_gaps(_rows(GAPS))[:4] == [
        "틀림 0/16 (목표 0)",
        "보류 0/16 (목표 2 이하)",
        "ANSWER 맞음 5/5 (목표 5)",
        "통과 16/16 (참고)",
    ]


# ---------- SCRUM-362 ★B3-5 — 판정은 자리표를 이름표 없이 값만 넣은 글에 (tools/ask_judge_text) ----------

P4 = next(i for i in PREMISE if i["id"] == "P4")


def _judged(it: dict, raw: str) -> tuple[str, str]:
    """(옛 규칙 — 맞음·틀림 둘 다 렌더링한 답, 지금 규칙 — 맞음은 렌더링한 답·틀림은 이름표 뺀 LLM 글) 판정(08 ★B3-5)."""
    svc, repo = build_service(FixedAnswer(recorded(), raw), facts=facts_for(it))
    res = svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))
    piece = extract(facts_for(it), it["rule_id"], res.generation_meta.bundles, load_display_labels())
    old = judge.verdict(it, res.status.value, res.answer)
    conflict, unclear = slot_direction_conflicts(raw, piece) > 0, slot_direction_unclear(raw, piece)
    new = judge.verdict(
        it, res.status.value, res.answer, judge_text(raw, piece, load_display_labels()), conflict, unclear
    )
    return old, new


def test_p4_v4_shape_correction_then_values_is_not_wrong() -> None:
    """① 바로잡은 뒤 출금 0건 자리표 + 입금 합계 자리표 한 문장 — 이름표 `출금 거래` 가 판정에 안 걸림."""
    raw = (
        "질문하신 출금 방향의 거래는 없어요. 이 케이스에는 {{outbound.count|이}} 확인되며, "
        "{{inbound.amount.USD|이}} 확인돼요."
    )
    assert _judged(P4, raw) == (judge.HOLD, judge.RIGHT)


def test_direction_word_with_opposite_slot_is_blocked_or_wrong() -> None:
    """② LLM 이 쓴 방향 낱말 + 반대 방향 자리표.

    ②a 그 키만이면 코드가 먼저 막음(`반대 방향 키만` → UNVERIFIED → 못 답함).
    ②b 출금 0건 자리표를 덧붙여 코드 검사를 지나도(전제 바로잡기 꼴) 판정은 틀림 — LLM 낱말 `출금은` 바로 뒤가 입금 키
    (`slot_direction_conflicts`, 추가 검토 1 H4). ★B3-5 규칙에서는 보류였음. 추가 검토 2 H3 부터는 0건 키가 뒤라 서비스가 먼저 막음.
    """
    assert _judged(P4, "출금은 {{inbound.amount.USD|이에요}}.") == (judge.NOT_ANSWERED, judge.NOT_ANSWERED)
    raw = "출금은 {{inbound.amount.USD|이에요}}. 그리고 {{outbound.count|이에요}}."
    assert _judged(P4, raw) == (
        judge.NOT_ANSWERED,
        judge.NOT_ANSWERED,
    )  # 추가 검토 2 H3 — 0건 키가 뒤라 서비스가 막음
