"""SCRUM-147 — draft_rewrite.try_rewrite 분기 10개 (attempted = 고쳐 쓰기 LLM 호출 보냈는가)."""

from __future__ import annotations

import pytest

from aml_ai.shared.errors import BudgetExceeded, LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.infrastructure.llm_client import LlmResult
from aml_ai.shared.schemas.str import JudgeMeta, NarrativeSection
from aml_ai.shared.schemas.str.narrative import SectionV2
from aml_ai.shared.schemas.str.verify import LlmCheckName
from tests.str.rewrite_support import (
    Clock,
    FakeJudge,
    FakeRewriter,
    JudgeOut,
    broken_narrative,
    call_try_rewrite,
    good_narrative,
)

_ALL_PASS = {n.value: 5 for n in LlmCheckName}


def _one_three(check=LlmCheckName.FIVE_W_ONE_H_COMPLETE):  # type: ignore[no-untyped-def]
    scores = dict(_ALL_PASS)
    scores[check.value] = 3
    return scores


def _run(judge, rewriter, narrative, *, clock=None, deadline=80.0):  # type: ignore[no-untyped-def]
    return call_try_rewrite(
        original_narrative=narrative,
        judge=judge,
        rewriter=rewriter,
        clock=clock or Clock(),
        deadline=deadline,
    )  # noqa: E501


def test_1_not_triggered_all_pass_scores() -> None:
    judge, rewriter = FakeJudge(JudgeOut(scores=_ALL_PASS, comments={})), FakeRewriter()
    meta, _, _ = _run(judge, rewriter, good_narrative())
    assert (meta.attempted, meta.applied, meta.skipped_reason) == (False, False, "not_triggered")
    assert meta.critique_scores == _ALL_PASS
    assert meta.critique_llm_model == "gpt-judge"
    assert rewriter.calls == 0


def test_2_applied_rewrite_narrative_passes_code_checks() -> None:
    judge = FakeJudge(JudgeOut(scores=_one_three(), comments={"FIVE_W_ONE_H_COMPLETE": "OPINION 반복"}))
    rewritten = good_narrative()
    rewritten[6] = NarrativeSection(
        section=SectionV2.OPINION,
        text="새로운 종합의견 문장. 조사역의 최종 판단이 필요함.",
        cites=["subject.entity_type"],
        evidence_ids=[],
    )
    rewriter = FakeRewriter(narrative=rewritten)
    meta, narrative, gen = _run(judge, rewriter, good_narrative())
    assert meta.attempted is True
    assert meta.applied is True
    assert meta.skipped_reason is None
    assert rewriter.calls == 1
    assert narrative[6].text.startswith("새로운 종합의견")
    for s in narrative:
        assert isinstance(s.evidence_ids, list)
    assert gen.tokens_in == 1200 + rewriter.tokens_in
    assert gen.tokens_out == 400 + rewriter.tokens_out
    assert gen.latency_ms == 5000 + rewriter.latency_ms


def test_3_rewrite_code_failed_returns_original() -> None:
    """SCRUM-147 추가 검토 — 본문은 원본, 토큰은 합산 (usage 받은 생성 모델 호출은 합산)."""
    judge = FakeJudge(JudgeOut(scores=_one_three(), comments={}))
    rewriter = FakeRewriter(narrative=broken_narrative())
    original = good_narrative()
    meta, narrative, gen = _run(judge, rewriter, original)
    assert meta.attempted is True
    assert meta.applied is False
    assert meta.skipped_reason == "rewrite_code_failed"
    assert rewriter.calls == 1
    assert narrative[6].text == original[6].text
    # 응답 받은 호출의 토큰은 합산 (★A 4 규칙 통일)
    assert gen.tokens_in == 1200 + rewriter.tokens_in
    assert gen.tokens_out == 400 + rewriter.tokens_out
    assert gen.latency_ms == 5000 + rewriter.latency_ms


def test_4_code_failed_original_skips_judge() -> None:
    judge, rewriter = FakeJudge(JudgeOut(scores=_ALL_PASS, comments={})), FakeRewriter()
    meta, _, _ = _run(judge, rewriter, broken_narrative())
    assert (meta.attempted, meta.applied, meta.skipped_reason) == (False, False, "code_failed")
    assert meta.critique_scores is None and meta.critique_llm_model is None
    assert judge.calls == 0 and rewriter.calls == 0


@pytest.mark.parametrize("exc", [LlmUnavailable("down"), LlmInvalidOutput("bad json"), RuntimeError("x")])
def test_5_critique_error_returns_original(exc: Exception) -> None:
    rewriter = FakeRewriter()
    meta, _, _ = _run(FakeJudge(exc), rewriter, good_narrative())
    assert (meta.attempted, meta.applied, meta.skipped_reason) == (False, False, "critique_error")
    assert meta.critique_scores is None and rewriter.calls == 0


def test_6a_budget_before_judge() -> None:
    # 남은 30 < LLM_TIMEOUT_S(35) — 평가자 앞 budget
    judge = FakeJudge(JudgeOut(scores=_ALL_PASS, comments={}))
    meta, _, _ = _run(judge, FakeRewriter(), good_narrative(), clock=Clock(50.0))
    assert meta.skipped_reason == "budget"
    assert meta.critique_scores is None and judge.calls == 0


class _AdvancingClock:
    """평가자 앞 선체크 OK → 평가자 뒤 체크 시 남은 < 35."""

    def __init__(self) -> None:
        self.step = 0

    def __call__(self) -> float:
        self.step += 1
        return 0.0 if self.step <= 1 else 50.0


def test_6b_budget_before_rewrite() -> None:
    judge, rewriter = FakeJudge(JudgeOut(scores=_one_three(), comments={})), FakeRewriter()
    meta, _, _ = _run(judge, rewriter, good_narrative(), clock=_AdvancingClock())
    assert meta.skipped_reason == "budget" and judge.calls == 1 and rewriter.calls == 0
    assert meta.critique_scores is not None  # 평가자는 돌았음


def test_7_schema_failure_no_retry() -> None:
    """usage 없는 스키마 실패 → 원본·토큰 미합산."""
    judge = FakeJudge(JudgeOut(scores=_one_three(), comments={}))
    rewriter = FakeRewriter(raise_exc=LlmInvalidOutput("rewrite schema failed"))
    meta, _, gen = _run(judge, rewriter, good_narrative())
    assert meta.attempted is True
    assert meta.applied is False
    assert meta.skipped_reason == "schema"
    assert rewriter.calls == 1
    assert gen.tokens_in == 1200  # usage 없음 → 원본 그대로


def test_7b_schema_failure_with_usage_merges_tokens() -> None:
    """SCRUM-147 추가 검토 — usage 받은 스키마 실패는 토큰 합산."""
    usage = LlmResult(text="{bad json}", model="gpt-rewrite", tokens_in=900, tokens_out=300, latency_ms=4200)
    rewriter = FakeRewriter(raise_exc=LlmInvalidOutput("schema"), raise_usage=usage)
    meta, _, gen = _run(FakeJudge(JudgeOut(scores=_one_three(), comments={})), rewriter, good_narrative())
    assert meta.skipped_reason == "schema"
    assert (gen.tokens_in, gen.tokens_out, gen.latency_ms) == (1200 + 900, 400 + 300, 5000 + 4200)


def test_8_call_count_cap_at_one_judge_one_rewrite() -> None:
    judge = FakeJudge(JudgeOut(scores=_one_three(), comments={}))
    rewriter = FakeRewriter(narrative=good_narrative())
    _run(judge, rewriter, good_narrative())
    assert judge.calls == 1
    assert rewriter.calls == 1


def test_9_verification_untouched() -> None:
    judge = FakeJudge(JudgeOut(scores=_ALL_PASS, comments={}))
    rewriter = FakeRewriter()
    meta, _, _ = _run(judge, rewriter, good_narrative())
    assert not hasattr(meta, "verification")


@pytest.mark.parametrize("exc", [LlmUnavailable("rewrite"), BudgetExceeded("daily"), RuntimeError("boom")])
def test_10_rewrite_error_keeps_original_and_200(exc: Exception) -> None:
    """고쳐 쓰기 호출 예외 → 원본·초안 200·rewrite_error. 실패 호출 토큰 최상위 합 제외."""
    judge = FakeJudge(JudgeOut(scores=_one_three(), comments={"FIVE_W_ONE_H_COMPLETE": "OPINION 반복"}))
    rewriter = FakeRewriter(raise_exc=exc)
    original = good_narrative()
    meta, narrative, gen = _run(judge, rewriter, original)
    assert meta.attempted is True
    assert meta.applied is False
    assert meta.skipped_reason == "rewrite_error"
    assert meta.critique_scores is not None
    assert narrative[0].text == original[0].text
    # 최상위 토큰·지연 = 생성만 — 실패한 고쳐 쓰기 호출 토큰 안 더함
    assert gen.tokens_in == 1200
    assert gen.tokens_out == 400
    assert gen.latency_ms == 5000


def test_11_critique_error_preserves_judge_meta_from_exception() -> None:
    """SCRUM-147 추가 검토 — 평가자 예외에 judge_meta 있으면 critique_* 보존 (scores=None)."""
    jm = JudgeMeta(
        llm_model="gpt-judge-partial",
        prompt_version="judge_v3",
        tokens_in=750,
        tokens_out=180,
        latency_ms=3800,
        attempts=1,
    )  # noqa: E501
    meta, _, gen = _run(FakeJudge(LlmInvalidOutput("x"), judge_meta=jm), FakeRewriter(), good_narrative())
    assert meta.skipped_reason == "critique_error" and meta.critique_scores is None
    assert meta.critique_llm_model == "gpt-judge-partial"
    assert (meta.critique_tokens_in, meta.critique_tokens_out, meta.critique_latency_ms) == (750, 180, 3800)
    assert gen.tokens_in == 1200  # 평가자 토큰은 critique_* 로 분리
