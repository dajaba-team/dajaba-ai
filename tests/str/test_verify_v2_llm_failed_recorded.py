"""v2 LLM_FAILED 경로 (SCRUM-61 당시 PASSED 였던 자리).

SCRUM-140(11/7): narrative v2 재녹화 2회 모두 OPINION 이 METHOD·GROUNDS 요약을 반복해
`FIVE_W_ONE_H_COMPLETE=3` → LLM_FAILED. PASSED 복구는 SCRUM-147 narrative_v2 고쳐 쓰기 뒤.
자세한 매트릭스·보류 사유는 docs/str/08 "verify 녹화 통합" + 09 SCRUM-140 결정 줄.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import VerifyResponse, VerifyStatus
from tests.str.verify_integration_support import (
    INTERNAL_KEY,
    create_draft,
    verify_body,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


def test_verify_v2_llm_failed_through_recorded(
    integration_client: TestClient,
    db_session: Session,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v2 녹화 — OPINION↔METHOD·GROUNDS 반복으로 FIVE_W=3 → LLM_FAILED (SCRUM-140, SCRUM-147 뒤 PASSED 복구)."""
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v2")
    get_settings.cache_clear()
    draft = create_draft(integration_client, draft_request_sample, "DRF-V-LLMF2")
    res = integration_client.post(
        "/v1/str/verify", json=verify_body(draft), headers={"X-Internal-Key": INTERNAL_KEY}
    )
    assert res.status_code == 200, res.text
    out = VerifyResponse.model_validate(res.json())
    assert out.status is VerifyStatus.LLM_FAILED and out.passed is False
    assert out.llm_checks is not None and len(out.llm_checks) == 5
    scored = {c.check.value: c.score for c in out.llm_checks}
    assert scored["FIVE_W_ONE_H_COMPLETE"] == 3
    assert out.narrative_refs is not None and len(out.narrative_refs) == 7
    assert all(set(ref.evidence_ids) <= {1, 2, 3} for ref in out.narrative_refs)
    assert out.judge_meta is not None and out.judge_meta.prompt_version == "judge_v2"
    assert out.verifier_version.endswith("+judge_v2")
    row = db_session.execute(
        text(
            "SELECT status, judge_llm_model, judge_tokens_in, judge_attempts"
            " FROM ai.verification_runs WHERE generation_id=:g"
        ),
        {"g": draft.generation_id},
    ).one()
    assert row.status == "LLM_FAILED" and row.judge_attempts == 1
    assert row.judge_llm_model and row.judge_tokens_in is not None
