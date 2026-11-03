"""SCRUM-59 Codex adversarial 회귀 — 잘못된 월·일·시·분 값은 전부 UNPARSED(verify 500 금지).

- 월 범위(13·0), 일 범위(2022-02-30·9월 31일·0일), 시 범위(25·오후 13시), 분 범위(99·12:60),
  ISO 결합(2022-13-01T00:00:00) — 전부 UNPARSED.
- `run_code_checks` 가 예외 없이 결과 리스트 반환.
- `VerifyService` 가 **500 아니라** CODE_FAILED 로 저장 (VerifyService 레벨 1건).
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CheckReason, CodeCheckName, SectionV1, VerifyStatus
from aml_ai.str.domain import verification
from tests.str.verification_support import date, facts_fan_in, section
from tests.str.verify_service_support import (
    FakeJudge,
    build_service,
    narrative_ok,
    stored_draft,
    verify_request,
)


@pytest.mark.parametrize(
    "text",
    [
        "2022년 13월 입금",  # 월 범위
        "2022년 0월 입금",  # 월 범위
        "0월 초 입금",  # 월 범위(vague)
        "13월 중순 입금",  # 월 범위(vague)
        "2022-13-01T00:00:00 입금",  # ISO 결합 월 범위
        "2022-02-30 입금",  # 일 범위
        "9월 31일 입금",  # 일 범위(KO_NOYEAR)
        "9월 0일 입금",
        "2022-09-02 25:00 입금",  # 시 범위
        "2022-09-02 오후 13시 30분 입금",  # 12시간제 밖
        "2022-09-02 12:60 입금",  # 분 범위
        "2022/09/02 23:99 입금",  # SLASH + 분 범위
        "2022.9.2 25:00 입금",  # DOT + 시 범위
        "9월 2일 25:00 입금",  # KO_NOYEAR + 시 범위
    ],
)
def test_invalid_values_produce_unparsed_without_exception(text: str) -> None:
    """잘못된 월·일·시·분 — 예외 안 던지고 전부 UNPARSED."""
    out = date(facts_fan_in(), SectionV1.SUMMARY, text)
    assert out, f"잘못된 값은 UNPARSED 로 결과에 남아야 함: {text!r}"
    assert all(c.reason is CheckReason.UNPARSED for c in out), [(c.draft_value, c.reason) for c in out]


def test_run_code_checks_does_not_raise_on_invalid_values() -> None:
    """verification.date_match 가 `run_code_checks` 안에서 예외 던지지 않음(SCRUM-91 회귀)."""
    narrative = [section(SectionV1.SUMMARY, "2022년 13월·9월 31일·오후 13시 — 전부 잘못된 값")]
    checks = verification.run_code_checks(facts_fan_in(), narrative, [1, 2, 3])
    kinds = {c.check for c in checks}
    assert CodeCheckName.DATE_MATCH in kinds


def test_verify_service_saves_code_failed_on_invalid_values() -> None:
    """★ VerifyService — 잘못된 값이 있는 본문 → CODE_FAILED 저장, 500 아님(SCRUM-91 회귀 유지).

    narrative_ok 를 재료로 WHO 섹션에 잘못된 날짜 하나를 끼워 넣어 UNPARSED → match=False → CODE_FAILED.
    """
    facts = facts_fan_in()
    narrative = narrative_ok()
    # WHO 섹션에 잘못된 월·일 추가 — scan_dates 가 UNPARSED 리턴, 결과 match=False → CODE_FAILED
    bad_who = narrative[1].model_copy(update={"text": narrative[1].text + " 2022년 13월 입금"})
    narrative[1] = bad_who
    draft = stored_draft(facts, narrative)
    judge = FakeJudge()  # 호출되지 않아야 함
    svc, verifications = build_service(judge=judge, draft=draft)

    resp = svc.verify(verify_request(narrative))

    assert resp.status is VerifyStatus.CODE_FAILED
    assert resp.passed is False
    assert resp.llm_checks is None
    assert judge.calls == 0  # 코드 실패 뒤엔 평가자 안 부름
    assert len(verifications.saved) == 1
    assert verifications.saved[0]["status"] is VerifyStatus.CODE_FAILED
