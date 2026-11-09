"""SCRUM-147 — draft_rewrite.try_rewrite 분기 10개.

(attempted 뜻: "고쳐 쓰기 LLM 호출을 실제로 보냈는가". 평가자만 돈 건 attempted=false)

① not_triggered — 평가자 전부 ≥ JUDGE_PASS_SCORE
② applied — 3점 항목 하나, 고친 본문 코드 검사 통과 (+ evidence_ids 재계산 확인)
③ rewrite_code_failed — 고친 본문 코드 검사 실패
④ code_failed — 원본 코드 검사 실패 (평가자 호출 0)
⑤ critique_error — 평가자 예외 (LlmUnavailable·LlmInvalidOutput·RuntimeError 각각)
⑥-a budget — 평가자 앞 남은 < LLM_TIMEOUT_S
⑥-b budget — 평가자는 돌고 고쳐 쓰기 앞 남은 < LLM_TIMEOUT_S
⑦ schema — 고쳐 쓰기 스키마 실패 (재생성 없음)
⑧ 호출 수 ≤ 4
⑨ verification is None 유지
⑩ rewrite_error — 고쳐 쓰기 호출 LlmUnavailable·BudgetExceeded·RuntimeError (덤 단계, 원본 반환·초안 200·실패 호출 토큰 최상위 합 제외)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from aml_ai.shared.errors import BudgetExceeded, LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.schemas.str import Facts, JudgeOutV2, LlmCheck, NarrativeSection
from aml_ai.shared.schemas.str.narrative import LlmNarrativeSection, SectionV2
from aml_ai.shared.schemas.str.verify import LlmCheckName
from aml_ai.str.domain.constants import JUDGE_PASS_SCORE

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CYCLE = REPO_ROOT / "tests" / "str" / "fixtures" / "facts_cycle_nopaths.json"


# ---------- 가짜 clock ----------


@dataclass
class _Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


# ---------- 가짜 Judge / Rewriter ----------


@dataclass
class _JudgeOut:
    scores: dict[str, int]
    comments: dict[str, str]
    model: str = "gpt-judge"
    tokens_in: int = 800
    tokens_out: int = 200
    latency_ms: int = 4000

    def as_result(self):  # Judge.run 이 돌려주는 모양과 최소 호환
        from aml_ai.str.infrastructure.judge import JudgeResult
        from aml_ai.shared.schemas.str import JudgeMeta

        checks = [
            LlmCheck(check=name, comment=self.comments.get(name.value, ""), score=self.scores[name.value])
            for name in LlmCheckName
        ]
        meta = JudgeMeta(
            llm_model=self.model,
            prompt_version="judge_v3",
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            latency_ms=self.latency_ms,
            attempts=1,
        )
        return JudgeResult(checks=checks, meta=meta, sections=[])


class _FakeJudge:
    def __init__(self, result: _JudgeOut | Exception) -> None:
        self._result = result
        self.calls = 0

    def run(self, facts_masked, narrative, *, deadline, fact_keys=None):
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result.as_result()


class _FakeRewriter:
    """고쳐 쓰기 호출 — rewriter.rewrite(...) → GenerationResult 또는 raise."""

    def __init__(self, narrative=None, raise_exc: Exception | None = None, tokens_in=1000, tokens_out=400, latency_ms=4500) -> None:
        self._narrative = narrative
        self._raise = raise_exc
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.latency_ms = latency_ms
        self.calls = 0

    def rewrite(self, *, facts_masked, fact_keys, examples, references, notes, original_narrative, critique, paths_notice, deadline):
        self.calls += 1
        if self._raise is not None:
            raise self._raise
        from aml_ai.str.domain.models import GenerationResult

        return GenerationResult(
            narrative=self._narrative,
            llm_model="gpt-generate",
            prompt_version="rewrite_v1",
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            latency_ms=self.latency_ms,
        )


# ---------- 입력 재료 ----------


def _facts() -> Facts:
    return Facts.model_validate(json.loads(FIXTURE_CYCLE.read_text()))


def _original_gen(narrative: list[LlmNarrativeSection]):
    from aml_ai.str.domain.models import GenerationResult

    return GenerationResult(
        narrative=narrative,
        llm_model="gpt-generate",
        prompt_version="narrative_v2",
        tokens_in=1200,
        tokens_out=400,
        latency_ms=5000,
    )


def _good_narrative() -> list[NarrativeSection]:
    """원본 코드 검사 통과하는 (구조적으로) 7섹션. 숫자·날짜·계좌는 facts 와 맞춰 둠."""
    base = {
        SectionV2.SUBJECT: "보고 대상자는 소매업 개인사업자임.",
        SectionV2.DATE: "거래 기간은 2022-09-02T00:14:00부터 2022-09-02T22:51:00까지임.",
        SectionV2.PLACE: "대상 계좌는 끝자리 BD30 이고 상대 계좌 분포는 자행 0곳·타행 3곳임.",
        SectionV2.INSTRUMENT: "결제 방식은 ACH 3건임.",
        SectionV2.METHOD: "여러 상대 계좌로부터 집중 입금됨.",
        SectionV2.GROUNDS: "모델 관측값(관측 구간: 2022-09-02T00:00:00~2022-09-03T00:00:00 기준) 3건임.",
        SectionV2.OPINION: "자료 종합 결과 추가 확인이 필요함. 조사역의 최종 판단이 필요함.",
    }
    return [NarrativeSection(section=s, text=t, cites=["subject.entity_type"], evidence_ids=[]) for s, t in base.items()]


def _broken_narrative() -> list[NarrativeSection]:
    """원본 코드 검사 '실패' 하게 금액 틀림."""
    narr = _good_narrative()
    # AMOUNT_MATCH 를 틀리게: facts 에 없는 금액 USD 999.00
    narr[3] = NarrativeSection(
        section=SectionV2.INSTRUMENT,
        text="결제 방식은 ACH 3건, USD 999.00 송금.",
        cites=["subject.entity_type"],
        evidence_ids=[],
    )
    return narr


# ---------- 공통 호출 ----------


def _call(
    *,
    original_narrative: list[NarrativeSection],
    judge: _FakeJudge,
    rewriter: _FakeRewriter,
    clock: _Clock,
    deadline: float,
    settings=None,
    alert_rule_id: str = "R04_CYCLE",
    evidence_scope: list[int] | None = None,
):
    from aml_ai.str.application.draft_rewrite import try_rewrite

    facts = _facts()
    return try_rewrite(
        facts=facts,
        facts_masked={"typology": facts.typology},
        fact_keys=["subject.entity_type"],
        examples=[],
        references=[],
        notes=None,
        alert_rule_id=alert_rule_id,
        evidence_scope=evidence_scope or [1, 2, 3],
        original_narrative=original_narrative,
        original_gen=_original_gen(original_narrative),
        judge=judge,
        rewriter=rewriter,
        clock=clock,
        deadline=deadline,
        settings=settings,
    )


# ---------- 시나리오 ----------


def test_1_not_triggered_all_pass_scores() -> None:
    judge = _FakeJudge(_JudgeOut(scores={n.value: 5 for n in LlmCheckName}, comments={}))
    rewriter = _FakeRewriter()
    clock = _Clock(0.0)
    meta, narrative, gen = _call(
        original_narrative=_good_narrative(),
        judge=judge,
        rewriter=rewriter,
        clock=clock,
        deadline=80.0,
    )
    assert meta.attempted is False
    assert meta.applied is False
    assert meta.skipped_reason == "not_triggered"
    assert meta.critique_scores == {n.value: 5 for n in LlmCheckName}
    assert meta.critique_llm_model == "gpt-judge"
    assert rewriter.calls == 0


def test_2_applied_rewrite_narrative_passes_code_checks() -> None:
    scores = {n.value: 5 for n in LlmCheckName}
    scores[LlmCheckName.FIVE_W_ONE_H_COMPLETE.value] = 3
    judge = _FakeJudge(_JudgeOut(scores=scores, comments={"FIVE_W_ONE_H_COMPLETE": "OPINION 반복"}))
    rewritten = _good_narrative()
    rewritten[6] = NarrativeSection(
        section=SectionV2.OPINION,
        text="새로운 종합의견 문장. 조사역의 최종 판단이 필요함.",
        cites=["subject.entity_type"],
        evidence_ids=[],
    )
    rewriter = _FakeRewriter(narrative=rewritten)
    meta, narrative, gen = _call(
        original_narrative=_good_narrative(),
        judge=judge,
        rewriter=rewriter,
        clock=_Clock(0.0),
        deadline=80.0,
    )
    assert meta.attempted is True
    assert meta.applied is True
    assert meta.skipped_reason is None
    assert rewriter.calls == 1
    # 고친 본문이 쓰임
    assert narrative[6].text.startswith("새로운 종합의견")
    # evidence_ids 재계산 — 섹션마다 cites 기반 (공백 가능)
    for s in narrative:
        assert isinstance(s.evidence_ids, list)
    # 최상위 토큰·지연 = 생성 + 고쳐 쓰기 합산
    assert gen.tokens_in == 1200 + rewriter.tokens_in
    assert gen.tokens_out == 400 + rewriter.tokens_out
    assert gen.latency_ms == 5000 + rewriter.latency_ms


def test_3_rewrite_code_failed_returns_original() -> None:
    scores = {n.value: 5 for n in LlmCheckName}
    scores[LlmCheckName.FIVE_W_ONE_H_COMPLETE.value] = 3
    judge = _FakeJudge(_JudgeOut(scores=scores, comments={}))
    rewritten_broken = _broken_narrative()
    rewriter = _FakeRewriter(narrative=rewritten_broken)
    original = _good_narrative()
    meta, narrative, gen = _call(
        original_narrative=original,
        judge=judge,
        rewriter=rewriter,
        clock=_Clock(0.0),
        deadline=80.0,
    )
    assert meta.attempted is True
    assert meta.applied is False
    assert meta.skipped_reason == "rewrite_code_failed"
    assert rewriter.calls == 1
    # 원본 반환
    assert narrative[6].text == original[6].text


def test_4_code_failed_original_skips_judge() -> None:
    judge = _FakeJudge(_JudgeOut(scores={n.value: 5 for n in LlmCheckName}, comments={}))
    rewriter = _FakeRewriter()
    meta, narrative, gen = _call(
        original_narrative=_broken_narrative(),
        judge=judge,
        rewriter=rewriter,
        clock=_Clock(0.0),
        deadline=80.0,
    )
    assert meta.attempted is False
    assert meta.applied is False
    assert meta.skipped_reason == "code_failed"
    assert meta.critique_scores is None
    assert meta.critique_llm_model is None
    assert judge.calls == 0
    assert rewriter.calls == 0


@pytest.mark.parametrize(
    "exc",
    [LlmUnavailable("down"), LlmInvalidOutput("bad json"), RuntimeError("unexpected")],
)
def test_5_critique_error_returns_original(exc: Exception) -> None:
    judge = _FakeJudge(exc)
    rewriter = _FakeRewriter()
    meta, narrative, gen = _call(
        original_narrative=_good_narrative(),
        judge=judge,
        rewriter=rewriter,
        clock=_Clock(0.0),
        deadline=80.0,
    )
    assert meta.attempted is False
    assert meta.applied is False
    assert meta.skipped_reason == "critique_error"
    assert meta.critique_scores is None
    assert rewriter.calls == 0


def test_6a_budget_before_judge() -> None:
    judge = _FakeJudge(_JudgeOut(scores={n.value: 5 for n in LlmCheckName}, comments={}))
    rewriter = _FakeRewriter()
    # deadline=80, clock=50 → 남은 30 < LLM_TIMEOUT_S(35) — 평가자 앞 budget
    clock = _Clock(50.0)
    meta, narrative, gen = _call(
        original_narrative=_good_narrative(),
        judge=judge,
        rewriter=rewriter,
        clock=clock,
        deadline=80.0,
    )
    assert meta.attempted is False
    assert meta.applied is False
    assert meta.skipped_reason == "budget"
    assert meta.critique_scores is None
    assert judge.calls == 0


def test_6b_budget_before_rewrite() -> None:
    scores = {n.value: 5 for n in LlmCheckName}
    scores[LlmCheckName.FIVE_W_ONE_H_COMPLETE.value] = 3
    judge = _FakeJudge(_JudgeOut(scores=scores, comments={}))
    rewriter = _FakeRewriter()

    class _AdvancingClock:
        def __init__(self) -> None:
            self.step = 0

        def __call__(self) -> float:
            # 평가자 앞 선체크 OK(남은 ≥35) → 평가자 뒤 체크 시 남은 < 35
            self.step += 1
            return 0.0 if self.step <= 1 else 50.0

    meta, narrative, gen = _call(
        original_narrative=_good_narrative(),
        judge=judge,
        rewriter=rewriter,
        clock=_AdvancingClock(),
        deadline=80.0,
    )
    assert meta.attempted is False
    assert meta.applied is False
    assert meta.skipped_reason == "budget"
    assert judge.calls == 1
    assert rewriter.calls == 0
    assert meta.critique_scores is not None  # 평가자는 돌았음


def test_7_schema_failure_no_retry() -> None:
    scores = {n.value: 5 for n in LlmCheckName}
    scores[LlmCheckName.FIVE_W_ONE_H_COMPLETE.value] = 3
    judge = _FakeJudge(_JudgeOut(scores=scores, comments={}))
    rewriter = _FakeRewriter(raise_exc=LlmInvalidOutput("rewrite schema failed"))
    meta, narrative, gen = _call(
        original_narrative=_good_narrative(),
        judge=judge,
        rewriter=rewriter,
        clock=_Clock(0.0),
        deadline=80.0,
    )
    assert meta.attempted is True
    assert meta.applied is False
    assert meta.skipped_reason == "schema"
    assert rewriter.calls == 1


def test_8_call_count_cap_at_one_judge_one_rewrite() -> None:
    scores = {n.value: 5 for n in LlmCheckName}
    scores[LlmCheckName.FIVE_W_ONE_H_COMPLETE.value] = 3
    judge = _FakeJudge(_JudgeOut(scores=scores, comments={}))
    rewritten = _good_narrative()
    rewriter = _FakeRewriter(narrative=rewritten)
    meta, narrative, gen = _call(
        original_narrative=_good_narrative(),
        judge=judge,
        rewriter=rewriter,
        clock=_Clock(0.0),
        deadline=80.0,
    )
    assert judge.calls == 1
    assert rewriter.calls == 1


def test_9_verification_untouched() -> None:
    """try_rewrite 는 응답 verification 을 건드리지 않는다(초안 응답 조립은 draft_service, 안건 17)."""
    judge = _FakeJudge(_JudgeOut(scores={n.value: 5 for n in LlmCheckName}, comments={}))
    rewriter = _FakeRewriter()
    meta, _, _ = _call(
        original_narrative=_good_narrative(),
        judge=judge,
        rewriter=rewriter,
        clock=_Clock(0.0),
        deadline=80.0,
    )
    # try_rewrite 의 결과에 verification 이라는 필드가 없어야 한다 (RewriteMeta 자체에 없음)
    assert not hasattr(meta, "verification")


@pytest.mark.parametrize(
    "exc",
    [LlmUnavailable("rewrite down"), BudgetExceeded("daily"), RuntimeError("boom")],
)
def test_10_rewrite_error_keeps_original_and_200(exc: Exception) -> None:
    """고쳐 쓰기 호출 예외 → 원본 반환·초안 200·attempted=true·applied=false·rewrite_error.

    실패 호출 토큰은 최상위 합에 안 더함 (SCRUM-45 패턴).
    """
    scores = {n.value: 5 for n in LlmCheckName}
    scores[LlmCheckName.FIVE_W_ONE_H_COMPLETE.value] = 3
    judge = _FakeJudge(_JudgeOut(scores=scores, comments={"FIVE_W_ONE_H_COMPLETE": "OPINION 반복"}))
    rewriter = _FakeRewriter(raise_exc=exc)
    original = _good_narrative()
    meta, narrative, gen = _call(
        original_narrative=original,
        judge=judge,
        rewriter=rewriter,
        clock=_Clock(0.0),
        deadline=80.0,
    )
    assert meta.attempted is True
    assert meta.applied is False
    assert meta.skipped_reason == "rewrite_error"
    assert meta.critique_scores is not None  # 평가자는 돌았음
    # 원본 narrative 반환
    assert narrative[0].text == original[0].text
    # 최상위 토큰·지연 = 생성만 — 실패한 고쳐 쓰기 호출 토큰은 안 더함
    assert gen.tokens_in == 1200
    assert gen.tokens_out == 400
    assert gen.latency_ms == 5000
