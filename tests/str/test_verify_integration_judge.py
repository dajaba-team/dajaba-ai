"""`/v1/str/verify` 녹화 통합 테스트 (SCRUM-61).

/drafts(생성 녹화 재생) → /verify(코드 5종 + judge_v2 녹화 재생) → 응답·DB 확인.
매트릭스·SCRUM-140 11/7 보류 사유는 docs/str/08 "verify 녹화 통합" 줄 + 09 SCRUM-140 결정 줄.
v2 LLM_FAILED 는 `test_verify_v2_llm_failed_recorded.py` 로 분리(관문 200 줄).
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
    replace_non_digit_word,
    verify_body,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


# ───────── v1 CODE_FAILED (SCRUM-140 재녹화 뒤 DATE_MATCH 3건 MISMATCH) ─────────


def test_verify_v1_code_failed_through_recorded(
    integration_client: TestClient,
    db_session: Session,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v1 녹화 — DATE_MATCH 3건 MISMATCH → CODE_FAILED (SCRUM-140, SCRUM-131 뒤 LLM_FAILED 복구)."""
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v1")
    get_settings.cache_clear()
    draft = create_draft(integration_client, draft_request_sample, "DRF-V-CODE1R")
    res = integration_client.post(
        "/v1/str/verify", json=verify_body(draft), headers={"X-Internal-Key": INTERNAL_KEY}
    )
    assert res.status_code == 200, res.text
    out = VerifyResponse.model_validate(res.json())
    assert out.status is VerifyStatus.CODE_FAILED
    assert out.passed is False
    assert out.llm_checks is None  # judge 안 부름
    assert out.narrative_refs is None
    assert out.judge_meta is None
    row = db_session.execute(
        text("SELECT status, judge_attempts FROM ai.verification_runs WHERE generation_id=:g"),
        {"g": draft.generation_id},
    ).one()
    assert row.status == "CODE_FAILED"


# ───────── CODE_FAILED (v1·v2 각각 — evidence 조작) ─────────


@pytest.mark.parametrize(
    ("prompt_name", "draft_id"),
    [("narrative_v1", "DRF-V-CODE1"), ("narrative_v2", "DRF-V-CODE2")],
)
def test_verify_code_failed_from_bad_evidence(
    integration_client: TestClient,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
    prompt_name: str,
    draft_id: str,
) -> None:
    """narrative evidence_ids 를 scope 밖으로 바꿔 EVIDENCE_IN_SCOPE 코드 검사 실패 → CODE_FAILED."""
    monkeypatch.setenv("NARRATIVE_PROMPT", prompt_name)
    get_settings.cache_clear()
    draft = create_draft(integration_client, draft_request_sample, draft_id)
    narrative = [s.model_dump(mode="json") for s in draft.narrative]
    narrative[0]["evidence_ids"] = [9999]  # scope = {1,2,3} 밖
    res = integration_client.post(
        "/v1/str/verify",
        json=verify_body(draft, narrative),
        headers={"X-Internal-Key": INTERNAL_KEY},
    )
    assert res.status_code == 200, res.text
    out = VerifyResponse.model_validate(res.json())
    assert out.status is VerifyStatus.CODE_FAILED
    assert out.llm_checks is None
    assert out.narrative_refs is None
    assert out.judge_meta is None


# ───────── VERIFY_UNAVAILABLE (judge 녹화 키 miss — 숫자 없는 단어 하나 변경) ─────────


@pytest.mark.parametrize(
    ("prompt_name", "draft_id"),
    [
        pytest.param(
            "narrative_v1",
            "DRF-V-UNAV1",
            marks=pytest.mark.xfail(
                reason=(
                    "SCRUM-140(11/7): v1 녹화 본문이 DATE_MATCH 3건 MISMATCH 라 전제('코드 통과') 깨짐 "
                    "→ VERIFY_UNAVAILABLE 가 아니라 CODE_FAILED 가 됨. "
                    "SCRUM-131 규칙 정리 뒤 복구"
                ),
                strict=True,
            ),
        ),
        ("narrative_v2", "DRF-V-UNAV2"),
    ],
)
def test_verify_unavailable_when_judge_key_missing(
    integration_client: TestClient,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
    prompt_name: str,
    draft_id: str,
) -> None:
    """숫자 없는 단어 하나만 다른 글자로 → 코드 검사(금액·날짜·건수·계좌) 통과·judge 녹화 키 miss."""
    monkeypatch.setenv("NARRATIVE_PROMPT", prompt_name)
    get_settings.cache_clear()
    draft = create_draft(integration_client, draft_request_sample, draft_id)
    narrative = [s.model_dump(mode="json") for s in draft.narrative]
    narrative[-1]["text"] = replace_non_digit_word(narrative[-1]["text"])
    res = integration_client.post(
        "/v1/str/verify",
        json=verify_body(draft, narrative),
        headers={"X-Internal-Key": INTERNAL_KEY},
    )
    assert res.status_code == 200, res.text
    out = VerifyResponse.model_validate(res.json())
    assert out.status is VerifyStatus.VERIFY_UNAVAILABLE
    assert out.llm_checks is None
    assert out.narrative_refs is None
    assert out.judge_meta is None  # LlmUnavailable 은 토큰 안 씀
