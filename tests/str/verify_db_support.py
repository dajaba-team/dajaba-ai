"""verify DB 테스트 공용 helper (SCRUM-57·91·92).

`test_verify_db.py`·`test_verify_db_judge_meta.py` 공용 — 공용 레코드·save·row 조회·assert.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheck,
    CodeCheckName,
    JudgeMeta,
    LlmCheck,
    LlmCheckName,
    VerifyStatus,
)
from aml_ai.str.infrastructure.verification_repository import VerificationRepository

SAMPLE_CODE_CHECKS = [
    CodeCheck(
        check=CodeCheckName.EVIDENCE_IN_SCOPE,
        section=None,
        draft_value="draft-X",
        source_value=None,
        match=False,
        reason=CheckReason.OUT_OF_SCOPE,
    ),
]
SAMPLE_LLM_CHECKS = [
    LlmCheck(check=LlmCheckName.FIVE_W_ONE_H_COMPLETE, comment="섹션 다 있음", score=5),
]
SAMPLE_SHA = "a" * 64


def save_code_failed(
    repo: VerificationRepository,
    *,
    request_id: str | None,
    judge_meta: JudgeMeta | None,
) -> str:
    """CODE_FAILED 샘플 저장 — judge_meta 전달 가능."""
    return repo.save(
        generation_id="g" * 32,
        draft_id="draft-57",
        revision_no=2,
        code_checks=SAMPLE_CODE_CHECKS,
        llm_checks=SAMPLE_LLM_CHECKS,
        passed=False,
        status=VerifyStatus.CODE_FAILED,
        verifier_version="judge_v1@test",
        narrative_sha256=SAMPLE_SHA,
        request_id=request_id,
        judge_meta=judge_meta,
    )


def save_passed_with_meta(
    repo: VerificationRepository,
    *,
    judge_meta: JudgeMeta,
) -> str:
    """PASSED 샘플 저장 — judge_meta 필수(SCRUM-92 5칸 왕복 테스트용)."""
    return repo.save(
        generation_id="g" * 32,
        draft_id="draft-92",
        revision_no=2,
        code_checks=SAMPLE_CODE_CHECKS,
        llm_checks=SAMPLE_LLM_CHECKS,
        passed=True,
        status=VerifyStatus.PASSED,
        verifier_version="verify-2026.11+judge_v1",
        narrative_sha256=SAMPLE_SHA,
        request_id=None,
        judge_meta=judge_meta,
    )


def read_run(engine: Engine, vid: str) -> object:
    """verification_runs 한 행 raw SELECT — judge_* 5칸 포함."""
    with engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT verification_id, generation_id, draft_id, revision_no, "
                "code_checks, llm_checks, passed, status, verifier_version, "
                "narrative_sha256, request_id, "
                "judge_llm_model, judge_tokens_in, judge_tokens_out, "
                "judge_latency_ms, judge_attempts, created_at "
                "FROM ai.verification_runs WHERE verification_id = :v"
            ),
            {"v": vid},
        ).one()


def read_judge_meta(engine: Engine, vid: str) -> object:
    """judge_* 5칸만 SELECT."""
    with engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT judge_llm_model, judge_tokens_in, judge_tokens_out, "
                "judge_latency_ms, judge_attempts "
                "FROM ai.verification_runs WHERE verification_id = :v"
            ),
            {"v": vid},
        ).one()


def assert_judge_meta_null(row: object) -> None:
    """judge_* 5칸 전부 NULL (CODE_FAILED·VERIFY_UNAVAILABLE 무토큰)."""
    assert row.judge_llm_model is None  # type: ignore[attr-defined]
    assert row.judge_tokens_in is None  # type: ignore[attr-defined]
    assert row.judge_tokens_out is None  # type: ignore[attr-defined]
    assert row.judge_latency_ms is None  # type: ignore[attr-defined]
    assert row.judge_attempts is None  # type: ignore[attr-defined]
