"""SCRUM-91 — VerifyService 상태 분기 테스트 (DB 없이, 가짜 저장소·judge). docs/str/06·03.

SCRUM-92 judge_meta 상세(LLM_FAILED 채움·VERIFY_UNAVAILABLE null 규칙·deadline)
는 `test_verify_service_judge_meta.py`.
"""

from __future__ import annotations

from aml_ai.shared.errors import LlmInvalidOutput, LlmUnavailable
from aml_ai.shared.schemas.str import VerifyStatus
from tests.str.verify_service_support import (
    FakeJudge,
    LogCall,
    build_service,
    facts_fan_in,
    judge_pass_checks,
    narrative_ok,
    stored_draft,
    verify_request,
)


def test_verify_passed() -> None:
    """정상 — 코드 전부 match + judge 모두 5점 → PASSED, save 1회, judge_meta 채움."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    judge = FakeJudge(checks=judge_pass_checks())
    svc, verifications = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.PASSED
    assert resp.passed is True
    assert resp.llm_checks is not None and len(resp.llm_checks) == 5
    assert resp.judge_meta is not None
    assert resp.judge_meta.prompt_version == "judge_v1"
    assert resp.judge_meta.attempts == 1
    assert judge.calls == 1
    assert len(verifications.saved) == 1
    saved = verifications.saved[0]
    assert saved["status"] is VerifyStatus.PASSED
    assert saved["judge_meta"] is not None
    assert saved["judge_meta"].attempts == 1


def test_verify_code_failed_skips_judge() -> None:
    """★ 진희 필수 — CODE_FAILED → judge 0회, judge_meta=None (응답·DB 둘 다)."""
    narrative = narrative_ok()
    # 첫 섹션에 범위 밖 ID 를 끼워 넣어 OUT_OF_SCOPE 유발
    narrative[0] = narrative[0].model_copy(update={"evidence_ids": [1, 2, 999]})
    draft = stored_draft(facts_fan_in(), narrative_ok())  # scope = {1,2,3}
    judge = FakeJudge(checks=judge_pass_checks())
    svc, verifications = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.CODE_FAILED
    assert resp.passed is False
    assert resp.llm_checks is None
    assert resp.judge_meta is None
    assert judge.calls == 0
    assert len(verifications.saved) == 1
    saved = verifications.saved[0]
    assert saved["llm_checks"] is None
    assert saved["judge_meta"] is None  # DB judge_* 5칸 전부 NULL


def test_verify_unexpected_exception_becomes_unavailable(judge_log: list[LogCall]) -> None:
    """★ SCRUM-91 — judge 가 RuntimeError → 500 아니라 VERIFY_UNAVAILABLE·save 1회."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    judge = FakeJudge(exc=RuntimeError("boom with 42,750.50 USD leaked"))
    svc, verifications = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.VERIFY_UNAVAILABLE
    assert resp.passed is False
    assert resp.llm_checks is None
    assert len(verifications.saved) == 1
    assert verifications.saved[0]["status"] is VerifyStatus.VERIFY_UNAVAILABLE
    assert verifications.saved[0]["llm_checks"] is None

    judge_calls = [c for c in judge_log if c.msg == "judge_unavailable"]
    assert len(judge_calls) == 1
    call = judge_calls[0]
    assert call.extra == {"reason": "RuntimeError"}
    # 민감 입력 유출 방지(SCRUM-15 adversarial H2)
    assert "42,750.50" not in call.msg
    assert not any("42,750.50" in str(v) for v in call.extra.values())


def test_verify_llm_unavailable_regression(judge_log: list[LogCall]) -> None:
    """회귀 — LlmUnavailable 은 그대로 VERIFY_UNAVAILABLE, reason 은 AiError.code."""
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    judge = FakeJudge(exc=LlmUnavailable("llm unavailable"))
    svc, _ = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.VERIFY_UNAVAILABLE
    call = [c for c in judge_log if c.msg == "judge_unavailable"][0]
    assert call.extra == {"reason": "LLM_UNAVAILABLE"}


def test_verify_llm_invalid_output_regression(judge_log: list[LogCall]) -> None:
    narrative = narrative_ok()
    draft = stored_draft(facts_fan_in(), narrative)
    judge = FakeJudge(exc=LlmInvalidOutput("bad json"))
    svc, _ = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.VERIFY_UNAVAILABLE
    call = [c for c in judge_log if c.msg == "judge_unavailable"][0]
    assert call.extra == {"reason": "LLM_INVALID_OUTPUT"}
