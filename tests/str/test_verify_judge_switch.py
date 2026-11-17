"""SCRUM-268 — v4 초안 verify 만 judge_v4, 스위치 상수 하나 (docs/str/06 "judge_v4", 09 SCRUM-268 사전 기준).

스위치 기본 = 꺼짐(judge_v3) · 켜면 `generations.prompt_version == narrative_v4` 만 judge_v4 · v2·버전 없음·꺼짐은
기존 평가자 · `verifier_version` 은 실제 고른 평가자 · `load_draft` 가 prompt_version 을 꺼냄(-m db).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import VerifyStatus
from aml_ai.str.application import verify_service as verify_module
from aml_ai.str.application.verify_service import VerifyService
from aml_ai.str.domain.constants import JUDGE_PROMPT, JUDGE_PROMPT_NARRATIVE_V4, JUDGE_PROMPT_V4, JUDGE_VOTES
from aml_ai.str.domain.models import StoredDraft
from aml_ai.str.infrastructure.generation_repository import GenerationRepository
from tests.str.verify_db_support import seed_draft
from tests.str.verify_service_support import (
    FakeGenerationRepository,
    FakeJudge,
    FakeVerificationRepository,
    facts_fan_in,
    judge_pass_checks,
    narrative_ok,
    stored_draft,
    verify_request,
)


def _draft(prompt_version: str | None) -> StoredDraft:
    return replace(stored_draft(facts_fan_in(), narrative_ok()), prompt_version=prompt_version)


def _service(
    draft: StoredDraft, v4: FakeJudge | None
) -> tuple[VerifyService, FakeJudge, FakeVerificationRepository]:
    get_settings.cache_clear()
    session = MagicMock()
    session.in_transaction.return_value = False
    default = FakeJudge(checks=judge_pass_checks(), prompt_version=JUDGE_PROMPT)
    saved = FakeVerificationRepository()
    svc = VerifyService(settings=get_settings(), session=session, generations=FakeGenerationRepository(draft=draft),
                        verifications=saved, judge=default, judge_for_v4=v4)  # type: ignore[arg-type]  # fmt: skip
    return svc, default, saved


def _v4_judge() -> FakeJudge:
    return FakeJudge(checks=judge_pass_checks(), prompt_version=JUDGE_PROMPT_V4)


def test_switch_is_off_at_merge() -> None:
    assert (JUDGE_PROMPT, JUDGE_PROMPT_V4) == ("judge_v3", "judge_v4")
    assert JUDGE_PROMPT_NARRATIVE_V4 == JUDGE_PROMPT  # 09 기준 1·2 충족 뒤 JUDGE_PROMPT_V4 로


def test_build_without_switch_has_no_v4_judge() -> None:
    svc = VerifyService.build(MagicMock(), get_settings())
    assert svc.judge_for_v4 is None and svc.judge.prompt_version == JUDGE_PROMPT


def test_build_with_switch_on_makes_v4_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(verify_module, "JUDGE_PROMPT_NARRATIVE_V4", JUDGE_PROMPT_V4)
    svc = VerifyService.build(MagicMock(), get_settings())
    assert svc.judge_for_v4 is not None
    assert svc.judge_for_v4.prompt_version == JUDGE_PROMPT_V4 and svc.judge_for_v4._votes == JUDGE_VOTES
    assert svc.judge.prompt_version == JUDGE_PROMPT


def test_v4_draft_uses_v4_judge() -> None:
    v4 = _v4_judge()
    svc, default, saved = _service(_draft("narrative_v4"), v4)
    resp = svc.verify(verify_request(narrative_ok()))
    assert (v4.calls, default.calls) == (1, 0)
    assert resp.status is VerifyStatus.PASSED
    assert (
        resp.verifier_version.endswith("+judge_v4")
        and saved.saved[0]["verifier_version"] == resp.verifier_version
    )


@pytest.mark.parametrize("prompt_version", ["narrative_v2", "narrative_v1", "narrative_v3", None])
def test_other_drafts_keep_default_judge(prompt_version: str | None) -> None:
    v4 = _v4_judge()
    svc, default, _ = _service(_draft(prompt_version), v4)
    resp = svc.verify(verify_request(narrative_ok()))
    assert (v4.calls, default.calls) == (0, 1)
    assert resp.verifier_version.endswith("+judge_v3")


def test_switch_off_v4_draft_keeps_default_judge() -> None:
    svc, default, _ = _service(_draft("narrative_v4"), None)
    resp = svc.verify(verify_request(narrative_ok()))
    assert default.calls == 1 and resp.verifier_version.endswith("+judge_v3")


def test_code_failed_v4_draft_records_chosen_judge() -> None:
    """코드 검사 실패면 평가자는 안 불림 — verifier_version 은 이 초안을 평가했을 평가자."""
    v4 = _v4_judge()
    draft = replace(_draft("narrative_v4"), evidence_transaction_ids=[])  # 범위 밖 → EVIDENCE_IN_SCOPE 실패
    svc, default, _ = _service(draft, v4)
    resp = svc.verify(verify_request(narrative_ok()))
    assert resp.status is VerifyStatus.CODE_FAILED and (v4.calls, default.calls) == (0, 0)
    assert resp.verifier_version.endswith("+judge_v4")


@pytest.mark.db
def test_load_draft_returns_prompt_version(db_session: Session, draft_request_sample: dict[str, Any],
                                           draft_response_sample: dict[str, Any]) -> None:  # fmt: skip
    gid = seed_draft(db_session, draft_request_sample, draft_response_sample)
    draft = GenerationRepository(db_session).load_draft(gid)
    assert draft is not None and draft.prompt_version == "narrative_v1"
