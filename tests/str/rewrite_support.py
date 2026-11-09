"""SCRUM-147 — test_draft_rewrite.py 공통 가짜 Judge·Rewriter·픽스처·_call."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from aml_ai.shared.schemas.str import Facts, JudgeMeta, LlmCheck, NarrativeSection
from aml_ai.shared.schemas.str.narrative import LlmNarrativeSection, SectionV2
from aml_ai.shared.schemas.str.verify import LlmCheckName
from aml_ai.str.domain.models import GenerationResult
from aml_ai.str.infrastructure.judge import JudgeResult

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_CYCLE = REPO_ROOT / "tests" / "str" / "fixtures" / "facts_cycle_nopaths.json"


@dataclass
class Clock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


@dataclass
class JudgeOut:
    scores: dict[str, int]
    comments: dict[str, str]
    model: str = "gpt-judge"
    tokens_in: int = 800
    tokens_out: int = 200
    latency_ms: int = 4000

    def as_result(self) -> JudgeResult:
        checks = [
            LlmCheck(check=n, comment=self.comments.get(n.value, ""), score=self.scores[n.value])
            for n in LlmCheckName
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


class FakeJudge:
    def __init__(self, result: JudgeOut | Exception) -> None:
        self._result = result
        self.calls = 0

    def run(self, facts_masked, narrative, *, deadline, fact_keys=None):  # type: ignore[no-untyped-def]
        self.calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result.as_result()


class FakeRewriter:
    def __init__(
        self,
        narrative: list[LlmNarrativeSection] | None = None,
        raise_exc: Exception | None = None,
        tokens_in: int = 1000,
        tokens_out: int = 400,
        latency_ms: int = 4500,
    ) -> None:
        self._narrative = narrative
        self._raise = raise_exc
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.latency_ms = latency_ms
        self.calls = 0

    def rewrite(self, **_kwargs) -> GenerationResult:  # type: ignore[no-untyped-def]
        self.calls += 1
        if self._raise is not None:
            raise self._raise
        return GenerationResult(
            narrative=self._narrative,
            llm_model="gpt-generate",
            prompt_version="rewrite_v1",
            tokens_in=self.tokens_in,
            tokens_out=self.tokens_out,
            latency_ms=self.latency_ms,
        )


def load_facts() -> Facts:
    return Facts.model_validate(json.loads(FIXTURE_CYCLE.read_text()))


def original_gen(narrative: list[NarrativeSection]) -> GenerationResult:
    return GenerationResult(
        narrative=narrative,
        llm_model="gpt-generate",
        prompt_version="narrative_v2",
        tokens_in=1200,
        tokens_out=400,
        latency_ms=5000,
    )


def good_narrative() -> list[NarrativeSection]:
    """원본 코드 검사 통과하는 7섹션."""
    base = {
        SectionV2.SUBJECT: "보고 대상자는 소매업 개인사업자임.",
        SectionV2.DATE: "거래 기간은 2022-09-02T00:14:00부터 2022-09-02T22:51:00까지임.",
        SectionV2.PLACE: "대상 계좌는 끝자리 BD30 이고 타행 3곳에서 입금됨.",
        SectionV2.INSTRUMENT: "결제 방식은 ACH 3건임.",
        SectionV2.METHOD: "여러 상대 계좌로부터 집중 입금됨.",
        SectionV2.GROUNDS: "모델 관측값(관측 구간: 2022-09-02T00:00:00~2022-09-03T00:00:00 기준) 3건임.",
        SectionV2.OPINION: "자료 종합 결과 추가 확인이 필요함. 조사역의 최종 판단이 필요함.",
    }
    return [
        NarrativeSection(section=s, text=t, cites=["subject.entity_type"], evidence_ids=[])
        for s, t in base.items()
    ]


def broken_narrative() -> list[NarrativeSection]:
    """AMOUNT_MATCH 실패: facts 에 없는 금액 USD 999.00."""
    narr = good_narrative()
    narr[3] = NarrativeSection(
        section=SectionV2.INSTRUMENT,
        text="결제 방식은 ACH 3건, USD 999.00 송금.",
        cites=["subject.entity_type"],
        evidence_ids=[],
    )
    return narr


def call_try_rewrite(
    *,
    original_narrative: list[NarrativeSection],
    judge: FakeJudge,
    rewriter: FakeRewriter,
    clock,  # type: ignore[no-untyped-def]
    deadline: float,
    settings=None,  # type: ignore[no-untyped-def]
    alert_rule_id: str = "R04_CYCLE",
    evidence_scope: list[int] | None = None,
):
    """try_rewrite 호출 — 공통 입력."""
    from aml_ai.str.application.draft_rewrite import try_rewrite

    facts = load_facts()
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
        original_gen=original_gen(original_narrative),
        judge=judge,
        rewriter=rewriter,
        clock=clock,
        deadline=deadline,
        settings=settings,
    )
