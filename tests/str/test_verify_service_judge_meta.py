"""SCRUM-92 — VerifyService judge_meta null 규칙·LLM_FAILED·DB 실패 토큰 유지.

PASSED·LLM_FAILED 는 judge_meta 채움, CODE_FAILED·VERIFY_UNAVAILABLE 응답은 null.
VERIFY_UNAVAILABLE 라도 1번째 시도 토큰을 썼으면 DB(save 인자)에는 남김(비용 추적 NFR-APR-03).
"""

from __future__ import annotations

from aml_ai.shared.errors import LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.schemas.str import JudgeMeta, LlmCheck, LlmCheckName, VerifyStatus
from aml_ai.str.infrastructure.judge import JudgeResult
from tests.str.verify_service_support import (
    FakeJudge,
    LogCall,
    build_service,
    facts_fan_in,
    judge_pass_meta,
    narrative_ok,
    stored_draft,
    verify_request,
)


def test_verify_llm_failed_sets_judge_meta() -> None:
    """★ SCRUM-92 — 점수 3점짜리가 하나 섞이면 LLM_FAILED. judge_meta 는 채워 저장·응답 둘 다."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    low_checks: list[LlmCheck] = [LlmCheck(check=n, comment="ok", score=5) for n in LlmCheckName]
    low_checks[0] = LlmCheck(check=LlmCheckName.FIVE_W_ONE_H_COMPLETE, comment="부족", score=3)
    judge = FakeJudge(result=JudgeResult(checks=low_checks, meta=judge_pass_meta(attempts=1)))
    svc, verifications = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.LLM_FAILED
    assert resp.passed is False
    assert resp.llm_checks is not None and len(resp.llm_checks) == 5
    assert resp.judge_meta is not None and resp.judge_meta.attempts == 1
    saved = verifications.saved[0]
    assert saved["status"] is VerifyStatus.LLM_FAILED
    assert saved["judge_meta"] is not None


def test_verify_llm_failed_two_attempts_meta_shows_both() -> None:
    """SCRUM-92 — 1번째 스키마 실패 뒤 2번째 성공 + 점수 미달 → LLM_FAILED.

    `attempts=2`, 토큰은 두 번 합. 실패해도 메타는 채워 저장·응답.
    """
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    low_checks: list[LlmCheck] = [LlmCheck(check=n, comment="ok", score=5) for n in LlmCheckName]
    low_checks[0] = LlmCheck(check=LlmCheckName.FIVE_W_ONE_H_COMPLETE, comment="부족", score=3)
    meta = JudgeMeta(
        llm_model="m2-last",
        prompt_version="judge_v1",
        tokens_in=1200 + 1800,
        tokens_out=300 + 600,
        latency_ms=3000 + 5000,
        attempts=2,
    )
    judge = FakeJudge(result=JudgeResult(checks=low_checks, meta=meta))
    svc, verifications = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.LLM_FAILED
    assert resp.judge_meta is not None
    assert resp.judge_meta.attempts == 2
    assert resp.judge_meta.tokens_in == 3000
    assert verifications.saved[0]["judge_meta"].attempts == 2


def test_verify_first_call_unavailable_judge_meta_null() -> None:
    """★ 진희 필수 — 1번째 호출이 LlmUnavailable → 응답·DB 모두 judge_meta=None.

    LlmUnavailable 은 재시도 없이 바로 올라와 `_decide()` 가 VERIFY_UNAVAILABLE.
    토큰을 쓰지 않았으므로 DB 저장 인자에도 judge_meta=None.
    """
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    judge = FakeJudge(exc=LlmUnavailable("llm unavailable"))
    svc, verifications = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.VERIFY_UNAVAILABLE
    assert resp.judge_meta is None
    saved = verifications.saved[0]
    assert saved["judge_meta"] is None  # DB judge_* 5칸 전부 NULL


def test_verify_unavailable_response_null_but_db_keeps_failed_tokens() -> None:
    """SCRUM-92 — 스키마 두 번 실패 → VERIFY_UNAVAILABLE. 응답 judge_meta=None,
    **DB 에는 실패 토큰까지 합산해 남김**(비용 추적 NFR-APR-03).

    예외에 meta 를 붙여 올리는 쪽이 자연스러움(`LlmInvalidOutput(..., judge_meta=...)` 속성 attach).
    """
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)

    exc = LlmInvalidOutput("judge output failed schema")
    exc.judge_meta = JudgeMeta(  # type: ignore[attr-defined]
        llm_model="m2-last",
        prompt_version="judge_v1",
        tokens_in=2500,
        tokens_out=700,
        latency_ms=7000,
        attempts=2,
    )
    judge = FakeJudge(exc=exc)
    svc, verifications = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.VERIFY_UNAVAILABLE
    assert resp.judge_meta is None  # 응답은 null
    saved = verifications.saved[0]
    assert saved["judge_meta"] is not None
    assert saved["judge_meta"].attempts == 2
    assert saved["judge_meta"].tokens_in == 2500


def test_verify_budget_exceeded_becomes_unavailable(judge_log: list[LogCall]) -> None:
    """SCRUM-92 — 남은 예산 < LLM_TIMEOUT_S → Judge 가 LlmUnavailable("verify budget exceeded").

    draft 와 같은 모양(새 예외 없음). 응답 VERIFY_UNAVAILABLE, judge_meta=None.
    """
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    judge = FakeJudge(exc=LlmUnavailable("verify budget exceeded"))
    svc, verifications = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.VERIFY_UNAVAILABLE
    assert resp.judge_meta is None
    assert verifications.saved[0]["judge_meta"] is None
    # 예산 초과도 LlmUnavailable 이므로 reason 은 AiError.code
    call = [c for c in judge_log if c.msg == "judge_unavailable"][0]
    assert call.extra == {"reason": "LLM_UNAVAILABLE"}


# ───────── SCRUM-144 — 실제 Judge + StubLlm 서비스 단위 ─────────


def test_verify_2nd_judge_call_exception_persists_1st_meta_to_db() -> None:
    """SCRUM-144 — 실제 `Judge` + `StubLlm` 로 "1차 스키마 실패 → 2차 complete_json 예외" 재현.

    서비스 응답은 `VERIFY_UNAVAILABLE`·`judge_meta=None` (SCRUM-92 규칙), DB 저장에는 1차 토큰이 남는다.
    """
    from aml_ai.shared.schemas.str import SectionV1
    from tests.str.judge_support import StubCall, StubLlm, make_judge

    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    stub = StubLlm(
        call_specs=[
            StubCall(text="not-json", tokens_in=1200, tokens_out=300, latency_ms=3000),
            StubCall(text="unused", exc=LlmUnavailable("timeout")),
        ]
    )
    judge = make_judge(stub, prompt_name="judge_v2", request_sections=[s.value for s in SectionV1])
    # build_service helper 재사용 — judge 만 실제로 교체
    svc, verifications = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.VERIFY_UNAVAILABLE
    assert resp.judge_meta is None, "응답 judge_meta 는 VERIFY_UNAVAILABLE 이면 null (SCRUM-92)"
    saved_meta = verifications.saved[0]["judge_meta"]
    assert saved_meta is not None, "DB 저장에는 1차 토큰이 남아야 (SCRUM-144)"
    assert saved_meta.attempts == 2, "보낸 호출 수"
    assert saved_meta.tokens_in == 1200
    assert saved_meta.tokens_out == 300
    assert saved_meta.latency_ms == 3000
    assert len(stub.calls) == 2
