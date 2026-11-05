"""verify_service·run_code_checks 테스트 공용 helper (SCRUM-91·92).

`test_verify_service.py`(상태 분기·judge_meta)·`test_verify_service_code_checks.py`(코드 검사) 공용.
리포 공유 패턴은 `verification_support.py`·`facts_support.py` 참조.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import (
    Facts,
    JudgeMeta,
    LlmCheck,
    LlmCheckName,
    RevisedNarrativeSection,
    VerifyRequest,
)
from aml_ai.str.application.verify_service import VerifyService
from aml_ai.str.domain.models import StoredDraft
from aml_ai.str.infrastructure.judge import JudgeResult
from tests.conftest import FIXTURES, load_json


@dataclass
class LogCall:
    """conftest.py `judge_log` fixture 가 수집하는 호출(log.warning 가로채기 결과)."""

    msg: str
    extra: dict


@dataclass
class FakeGenerationRepository:
    draft: StoredDraft | None

    def load_draft(self, generation_id: str) -> StoredDraft | None:
        return self.draft


@dataclass
class FakeVerificationRepository:
    saved: list[dict] = field(default_factory=list)

    def save(self, **kwargs: Any) -> str:
        self.saved.append(kwargs)
        return "verif-" + str(len(self.saved))


@dataclass
class FakeJudge:
    """`Judge.run` 과 같은 시그니처 — SCRUM-92 에서 `JudgeResult` 반환.

    `result` 가 있으면 그걸 리턴, `exc` 가 있으면 예외, 둘 다 없으면 `checks` 로 조립.
    """

    checks: list[LlmCheck] | None = None
    result: JudgeResult | None = None
    exc: BaseException | None = None
    prompt_version: str = "judge_v2"
    calls: int = 0
    received_fact_keys: list[str] | None = None

    def run(
        self,
        facts_masked: dict,
        narrative: list,
        *,
        deadline: float | None = None,
        fact_keys: list[str] | None = None,
    ) -> JudgeResult:
        """SCRUM-61 — `fact_keys` 인자 받음. v2 Judge 실제 시그니처와 맞춤."""
        self.calls += 1
        self.received_fact_keys = fact_keys
        if self.exc is not None:
            raise self.exc
        if self.result is not None:
            return self.result
        assert self.checks is not None
        return JudgeResult(checks=self.checks, meta=judge_pass_meta(), sections=[])


def judge_pass_meta(*, attempts: int = 1, tokens_in: int = 1800, tokens_out: int = 600) -> JudgeMeta:
    """PASSED·LLM_FAILED 예시에 쓰는 기본 meta."""
    return JudgeMeta(
        llm_model="stub-judge",
        prompt_version="judge_v1",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=8000,
        attempts=attempts,
    )


def facts_fan_in() -> Facts:
    return Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))


def narrative_ok() -> list[RevisedNarrativeSection]:
    """fan_in 본문 — v1 6섹션, cites·evidence_ids 범위 안(EVIDENCE_IN_SCOPE match)."""
    raw = load_json(FIXTURES / "narrative_ok.json")["narrative"]
    return [RevisedNarrativeSection.model_validate(s) for s in raw]


def judge_pass_checks() -> list[LlmCheck]:
    return [LlmCheck(check=n, comment="ok", score=5) for n in LlmCheckName]


def stored_draft(facts: Facts, narrative: list[RevisedNarrativeSection]) -> StoredDraft:
    scope = sorted({tid for s in narrative for tid in s.evidence_ids})
    return StoredDraft(
        generation_id="g" * 32,
        draft_id="draft-91",
        facts=facts,
        evidence_transaction_ids=scope,
        references=[],
    )


def verify_request(narrative: list[RevisedNarrativeSection]) -> VerifyRequest:
    return VerifyRequest(generation_id="g" * 32, revision_no=1, narrative=narrative)


def build_service(
    *, judge: FakeJudge, draft: StoredDraft
) -> tuple[VerifyService, FakeVerificationRepository]:
    get_settings.cache_clear()
    verifications = FakeVerificationRepository()
    svc = VerifyService(
        settings=get_settings(),
        generations=FakeGenerationRepository(draft=draft),
        verifications=verifications,
        judge=judge,
    )
    return svc, verifications
