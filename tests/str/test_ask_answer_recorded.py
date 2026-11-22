"""ask_answer_v2 녹화 재생 — 평가 세트 범위 안 12개 + 오류 주입 2 (SCRUM-290 2/2 · 358·359 v2, 정본 docs/str/08).

계획(ask_plan_v1)·답(ask_answer_v2) 둘 다 녹화 재생, facts 는 평가 세트의 픽스처 주입(서비스 수준 — 질문 답변 전용
복사본이 있으면 그것). 목표(08 12.2, 결과 보기 전 고정 — v2 에서도 그대로): 사실 8/8 `ANSWERED` · 범위 안 12개 중
`UNVERIFIED` 1개 이하. v1 녹화(`recorded/ask_answer_v1/`)는 기록으로 남김(지우지도 고치지도 않음).
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import AskStatus
from tests.str.ask_recorded_support import (
    IN_SCOPE,
    OUT_OF_CHECK_SENTENCE,
    AnswerRewrite,
    add_out_of_check_number,
    bump_first_count,
    facts_for,
    item,
    recorded,
)
from tests.str.ask_service_support import ask_request, build_service

IN_SCOPE_STATES = {AskStatus.ANSWERED, AskStatus.NO_DATA, AskStatus.UNVERIFIED}


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _ask(it: dict, llm=None):
    svc, repo = build_service(llm or recorded(), facts=facts_for(it))
    return svc.ask(ask_request(it["question"], rule_id=it["rule_id"])), repo


@pytest.mark.parametrize("it", IN_SCOPE, ids=lambda i: i["id"])
def test_in_scope_replay_ends_in_scope_and_saves(it: dict) -> None:
    res, repo = _ask(it)
    assert res.status in IN_SCOPE_STATES
    assert res.kind.value == it["expected_kind"]
    assert it["expected_bundle"] in res.generation_meta.bundles
    assert repo.saved[0]["status"] == "SUCCEEDED" and "llm_answer" in repo.saved[0]["response_payload"]


def test_eval_targets_fact_answered_and_unverified_at_most_one() -> None:
    """08 목표 — 결과를 본 뒤 바꾸지 않는다."""
    states = {it["id"]: _ask(it)[0].status for it in IN_SCOPE}
    facts_ok = [i for i, s in states.items() if i.startswith("F") and s is AskStatus.ANSWERED]
    unverified = [i for i, s in states.items() if s is AskStatus.UNVERIFIED]
    assert len(facts_ok) == 8, states
    assert len(unverified) <= 1, states


def test_injected_wrong_count_is_unverified_and_body_only_in_row() -> None:
    """오류 주입 ① — F1 녹화 답의 건수를 바꾸면 UNVERIFIED, 응답엔 본문 없음·저장 행엔 있음."""
    res, repo = _ask(item("F1"), AnswerRewrite(recorded(), bump_first_count))
    assert res.status is AskStatus.UNVERIFIED
    assert (res.answer, res.cites, res.evidence_ids) == (None, [], [])
    assert any(c.check.value == "COUNT_MATCH" and not c.match for c in res.code_checks)
    saved = repo.saved[0]["response_payload"]["llm_answer"]["answer"]
    assert saved and saved not in res.model_dump_json()


def test_injected_out_of_check_number_passes_known_limit() -> None:
    """오류 주입 ② — 검사 밖 문맥(은행 수)의 틀린 숫자는 통과한다(06·09 알고 남김)."""
    res, _ = _ask(item("F1"), AnswerRewrite(recorded(), add_out_of_check_number))
    assert res.status is AskStatus.ANSWERED
    assert res.answer.endswith(OUT_OF_CHECK_SENTENCE)
