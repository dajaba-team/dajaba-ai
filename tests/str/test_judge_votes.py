"""SCRUM-207 — Judge N 중앙값 집계 단위 테스트 (verify 경로 전용, docs/str/06).

- 세 호출 다른 점수 → 항목별 median · judge_meta attempts·tokens 합(스키마 실패 포함)·latency max
- 짝수(2 성공)면 두 값 중 낮은 점수
- 성공 <2 면 LlmUnavailable → verify_service 가 VERIFY_UNAVAILABLE
- BudgetExceeded 한 호출 → 즉시 전체 중단
- comment: 항목별 median 낸 호출 중 run 번호 작은 쪽
- narrative_refs(sections): run 1 호출 그대로
- 녹화 같은 응답 3회 → 중앙값과 같음(녹화 테스트 보전)

develop 에서는 `Judge(..., votes=3)` TypeError 또는 1회 호출만 돌아 median != 기대값 — 실패해야 정상.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.errors import BudgetExceeded, LlmUnavailable
from aml_ai.str.domain.constants import JUDGE_VOTES
from tests.str.judge_votes_support import (
    CHECK_NAMES,
    SECTIONS_V2,
    ThreadSafeStub,
    VoteCall,
    dummy_narrative,
    make_judge,
    v3_payload,
)

# 기존 테스트가 썼던 이름 유지 — _v3_payload·_dummy_narrative·_make_judge 로 wrap.
_v3_payload = v3_payload
_dummy_narrative = dummy_narrative
_make_judge = make_judge


def test_judge_votes_default_constant_is_three() -> None:
    """상수는 3. draft 경로 Judge(votes=1 기본)과 수평."""
    assert JUDGE_VOTES == 3


def test_three_calls_item_wise_median_tokens_sum_latency_max() -> None:
    """세 호출 다른 점수 → 항목별 median · tokens 합(응답 받은 호출 전부) · latency max."""
    stub = ThreadSafeStub([
        VoteCall(text=_v3_payload([5, 5, 5, 5, 5], comment_tag="r1"), tokens_in=1000, tokens_out=400, latency_ms=5000),
        VoteCall(text=_v3_payload([3, 5, 5, 5, 5], comment_tag="r2"), tokens_in=1100, tokens_out=410, latency_ms=7000),
        VoteCall(text=_v3_payload([1, 5, 5, 5, 5], comment_tag="r3"), tokens_in=1200, tokens_out=420, latency_ms=6000),
    ])  # fmt: skip
    judge = _make_judge(stub)
    result = judge.run(facts_masked={}, narrative=_dummy_narrative(), fact_keys=[])
    scores = {c.check.value: c.score for c in result.checks}
    assert scores["FIVE_W_ONE_H_COMPLETE"] == 3  # median of 5·3·1
    assert all(scores[n] == 5 for n in CHECK_NAMES if n != "FIVE_W_ONE_H_COMPLETE")
    assert result.meta.attempts == 3  # 보낸 호출 수 합 (각 1)
    assert result.meta.tokens_in == 1000 + 1100 + 1200
    assert result.meta.tokens_out == 400 + 410 + 420
    assert result.meta.latency_ms == 7000  # 최대값


def test_comment_from_lowest_run_that_matched_median() -> None:
    """comment 는 항목별 median 과 같은 점수를 낸 호출 중 run 번호 작은 쪽.

    run 1 점수가 median 과 다른 경우 — 1단계(1회 호출) 상태에서는 r1 이 나와 실패해야 한다.
    """
    stub = ThreadSafeStub([
        VoteCall(text=_v3_payload([5, 5, 5, 5, 5], comment_tag="r1")),  # FIVE_W=5 (median 과 다름)
        VoteCall(text=_v3_payload([3, 5, 5, 5, 5], comment_tag="r2")),  # FIVE_W=3 ← comment 이거
        VoteCall(text=_v3_payload([3, 5, 5, 5, 5], comment_tag="r3")),  # FIVE_W=3
    ])  # fmt: skip
    judge = _make_judge(stub)
    result = judge.run(facts_masked={}, narrative=_dummy_narrative(), fact_keys=[])
    by_check = {c.check.value: c for c in result.checks}
    # FIVE_W median = 3. 3을 낸 run 중 번호 작은 쪽 = run 2 → "r2-FIVE_W_ONE_H_COMPLETE".
    assert by_check["FIVE_W_ONE_H_COMPLETE"].comment == "r2-FIVE_W_ONE_H_COMPLETE"


def test_sections_from_run_one_regardless_of_median() -> None:
    """narrative_refs(sections) 는 run 1 호출의 것을 그대로."""
    run1_sections = [{"section": s, "cites": [f"k1-{s}"]} for s in SECTIONS_V2]
    run2_sections = [{"section": s, "cites": [f"k2-{s}"]} for s in SECTIONS_V2]
    stub = ThreadSafeStub([
        VoteCall(text=_v3_payload([3, 5, 5, 5, 5], sections=run1_sections)),
        VoteCall(text=_v3_payload([5, 5, 5, 5, 5], sections=run2_sections)),
        VoteCall(text=_v3_payload([5, 5, 5, 5, 5], sections=run2_sections)),
    ])  # fmt: skip
    judge = _make_judge(stub)
    result = judge.run(facts_masked={}, narrative=_dummy_narrative(), fact_keys=[])
    cites_by_section = {s.section.value: list(s.cites) for s in result.sections}
    for s in SECTIONS_V2:
        assert cites_by_section[s] == [f"k1-{s}"]  # run 1 그대로


def test_two_success_one_unavailable_lower_of_two_on_even() -> None:
    """3 중 1 LlmUnavailable → 성공 2 집계, 짝수라 두 점수 중 낮은 쪽."""
    stub = ThreadSafeStub([
        VoteCall(text=_v3_payload([5, 5, 5, 5, 5])),
        VoteCall(text=_v3_payload([3, 5, 5, 5, 5])),  # 둘 중 낮은 쪽
        VoteCall(exc=LlmUnavailable("down")),
    ])  # fmt: skip
    judge = _make_judge(stub)
    result = judge.run(facts_masked={}, narrative=_dummy_narrative(), fact_keys=[])
    scores = {c.check.value: c.score for c in result.checks}
    assert scores["FIVE_W_ONE_H_COMPLETE"] == 3  # min(5,3)
    assert result.meta.attempts == 3


def test_two_unavailable_raises_llm_unavailable() -> None:
    """3 중 2 LlmUnavailable (성공 <2) → Judge.run 이 LlmUnavailable raise → verify 쪽 VERIFY_UNAVAILABLE."""
    stub = ThreadSafeStub([
        VoteCall(text=_v3_payload([5, 5, 5, 5, 5])),
        VoteCall(exc=LlmUnavailable("down-1")),
        VoteCall(exc=LlmUnavailable("down-2")),
    ])  # fmt: skip
    judge = _make_judge(stub)
    with pytest.raises(LlmUnavailable):
        judge.run(facts_masked={}, narrative=_dummy_narrative(), fact_keys=[])


def test_budget_exceeded_short_circuits_all() -> None:
    """한 호출 BudgetExceeded → 즉시 전체 중단, 남은 호출 cancel."""
    stub = ThreadSafeStub([
        VoteCall(text=_v3_payload([5, 5, 5, 5, 5])),
        VoteCall(exc=BudgetExceeded("quota")),
        VoteCall(text=_v3_payload([5, 5, 5, 5, 5])),
    ])  # fmt: skip
    judge = _make_judge(stub)
    with pytest.raises(BudgetExceeded):
        judge.run(facts_masked={}, narrative=_dummy_narrative(), fact_keys=[])


def test_schema_fail_counts_tokens_but_retries_once() -> None:
    """스키마 실패해도 응답 받은 호출의 tokens 는 judge_meta 에 합산 (SCRUM-144·92).

    각 호출은 schema_retry=1. 1차 스키마 실패 + 2차 성공이면 attempts 2·tokens 두 번 합.
    세 호출 다 "1 스키마 + 1 성공" 이면 attempts=6, tokens 6회 합.
    """
    good = _v3_payload([5, 5, 5, 5, 5])
    bad = "not-judge-json"
    stub = ThreadSafeStub([
        VoteCall(text=bad, tokens_in=100, tokens_out=50),   # 호출 1 - 1차 스키마 실패
        VoteCall(text=good, tokens_in=1000, tokens_out=400),  # 호출 1 - 2차 성공
        VoteCall(text=bad, tokens_in=100, tokens_out=50),
        VoteCall(text=good, tokens_in=1000, tokens_out=400),
        VoteCall(text=bad, tokens_in=100, tokens_out=50),
        VoteCall(text=good, tokens_in=1000, tokens_out=400),
    ])  # fmt: skip
    judge = _make_judge(stub)
    result = judge.run(facts_masked={}, narrative=_dummy_narrative(), fact_keys=[])
    assert result.meta.attempts == 6
    assert result.meta.tokens_in == (100 + 1000) * 3
    assert result.meta.tokens_out == (50 + 400) * 3


def test_all_three_same_response_matches_single_call() -> None:
    """녹화 재생 흉내 — 같은 user 라 세 호출 다 같은 응답. median == 그 응답."""
    text = _v3_payload([5, 5, 5, 5, 5])
    stub = ThreadSafeStub([VoteCall(text=text) for _ in range(3)])
    judge = _make_judge(stub)
    result = judge.run(facts_masked={}, narrative=_dummy_narrative(), fact_keys=[])
    assert all(c.score == 5 for c in result.checks)
    assert result.meta.attempts == 3


def test_votes_one_is_single_call_baseline() -> None:
    """votes=1 이면 지금 동작과 같음 — 호출 1회, median 없음."""
    stub = ThreadSafeStub([VoteCall(text=_v3_payload([3, 5, 5, 5, 5]))])
    judge = _make_judge(stub, votes=1)
    result = judge.run(facts_masked={}, narrative=_dummy_narrative(), fact_keys=[])
    assert result.meta.attempts == 1
    assert result.checks[0].score == 3  # 응답 그대로
