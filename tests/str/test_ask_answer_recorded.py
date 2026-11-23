"""답 녹화 재생 — 평가 세트 범위 안 12개 + 오류 주입 2 (SCRUM-290 2/2 · SCRUM-362 ask_answer_v6, 정본 docs/str/08).

계획(ask_plan_v1)·답(ask_answer_v6) 둘 다 녹화 재생, facts 는 평가 세트의 픽스처 주입(서비스 수준 — 질문 답변 전용
복사본이 있으면 그것). 목표(08 12.2, 결과 보기 전 고정): 사실 8/8 `ANSWERED` · 범위 안 12개 중 `UNVERIFIED` 1개 이하
(SCRUM-362 세 세트 목표 0/38). v1·v2·v3 녹화는 기록으로 남김(지우지도 고치지도 않음). W2 는 `--only W2` 로 저장(계획 다름 뒤).
"""

from __future__ import annotations

import re

import pytest

from aml_ai.shared.schemas.str import AskStatus
from tests.str.ask_recorded_support import (
    IN_SCOPE,
    OUT_OF_CHECK_SENTENCE,
    AnswerRewrite,
    add_out_of_check_number,
    facts_for,
    item,
    recorded,
)
from tests.str.ask_service_support import ask_request, build_service


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _ask(it: dict, llm=None):
    svc, repo = build_service(llm or recorded(), facts=facts_for(it))
    return svc.ask(ask_request(it["question"], rule_id=it["rule_id"])), repo


@pytest.mark.parametrize("it", IN_SCOPE, ids=lambda i: i["id"])
def test_v6_replay_answered_and_saves(it: dict) -> None:
    """08 "결과 — v6 녹화" — 12개 모두 ANSWERED, 답은 렌더링한 문장(자리표 없음)·저장 행 원문은 자리표 그대로."""
    res, repo = _ask(it)
    assert res.status is AskStatus.ANSWERED, it["id"]
    assert res.kind.value == it["expected_kind"]
    assert it["expected_bundle"] in res.generation_meta.bundles
    assert "{{" not in res.answer and "{{" in repo.saved[0]["response_payload"]["llm_answer"]["answer"]


def test_eval_targets_fact_answered_and_unverified_zero() -> None:
    """08 목표 — 결과를 본 뒤 바꾸지 않는다."""
    states = {it["id"]: _ask(it)[0].status for it in IN_SCOPE}
    facts_ok = [i for i, s in states.items() if i.startswith("F") and s is AskStatus.ANSWERED]
    assert len(facts_ok) == 8, states
    assert [i for i, s in states.items() if s is AskStatus.UNVERIFIED] == [], states


def _swap_first_slot_key(out: dict) -> dict:
    """오류 주입 ①(v5 꼴) — 첫 자리표 키를 묶음 밖 키로. 자리표가 없으면 테스트가 실패하도록 AssertionError."""
    answer = out["answer"] or ""
    assert "{{" in answer, "녹화 답에 자리표가 없음"
    return {**out, "answer": re.sub(r"\{\{[^{}|]*", "{{paths.count", answer, count=1)}


def test_injected_out_of_bundle_key_is_unverified_and_body_only_in_row() -> None:
    """오류 주입 ① — F1 답의 자리표 키를 묶음 밖으로 바꾸면 UNVERIFIED(범위 밖), 응답엔 본문 없음·저장 행엔 있음."""
    res, repo = _ask(item("F1"), AnswerRewrite(recorded(), _swap_first_slot_key))
    assert res.status is AskStatus.UNVERIFIED
    assert (res.answer, res.cites, res.evidence_ids) == (None, [], [])
    assert res.code_checks[0].draft_value == "인용 키 범위 밖 1개"
    assert "{{paths.count" in repo.saved[0]["response_payload"]["llm_answer"]["answer"]


def test_injected_out_of_check_number_is_now_unverified() -> None:
    """오류 주입 ② — 검사 밖 문맥의 숫자(은행 7곳)를 덧붙이면: v2 는 ANSWERED(알고 남김), v4 는 자리표 밖 숫자로 UNVERIFIED."""
    res, repo = _ask(item("F1"), AnswerRewrite(recorded(), add_out_of_check_number))
    assert res.status is AskStatus.UNVERIFIED
    assert res.code_checks[0].draft_value == "자리표 밖 숫자 1개"
    assert repo.saved[0]["response_payload"]["llm_answer"]["answer"].endswith(OUT_OF_CHECK_SENTENCE)
