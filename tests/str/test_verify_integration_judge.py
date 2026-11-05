"""`/v1/str/verify` 녹화 통합 테스트 (SCRUM-61).

흐름 — /drafts(생성 녹화 재생) → /verify(코드 5종 + judge_v2 녹화 재생) → 응답·DB 확인.
매트릭스: v1 = LLM_FAILED·CODE_FAILED·VERIFY_UNAVAILABLE / v2 = PASSED·CODE_FAILED·VERIFY_UNAVAILABLE.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import DraftResponse, VerifyResponse, VerifyStatus
from tests.str.integration_support import INTEGRATION_INTERNAL_KEY

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
INTERNAL_KEY = INTEGRATION_INTERNAL_KEY


def _draft_body(sample: dict, draft_id: str) -> dict:
    body = {**sample}
    body["draft_id"] = draft_id
    body["alert"] = {
        **body["alert"],
        "account_key": "010_8000EBD30",
        "entity_id": "80062E240",
        "transaction_ids": [1, 2, 3],
    }
    body["evidence_transaction_ids"] = [1, 2, 3]
    body["investigator_notes"] = None
    return body


def _create_draft(client: TestClient, sample: dict, draft_id: str) -> DraftResponse:
    body = _draft_body(sample, draft_id)
    res = client.post("/v1/str/drafts", json=body, headers={"X-Internal-Key": INTERNAL_KEY})
    assert res.status_code == 200, res.text
    return DraftResponse.model_validate(res.json())


def _verify_body(draft: DraftResponse, narrative_override: list | None = None) -> dict:
    sections = narrative_override or [s.model_dump(mode="json") for s in draft.narrative]
    return {"generation_id": draft.generation_id, "revision_no": 1, "narrative": sections}


def _replace_non_digit_word(text_value: str) -> str:
    """숫자 없는 단어 하나만 다른 글자로 — 코드 검사(금액·날짜·건수·계좌) 영향 없음."""
    tokens = text_value.split()
    for i, tok in enumerate(tokens):
        stripped = tok.strip(".,;:()[]{}")
        if stripped and not any(ch.isdigit() for ch in stripped):
            tokens[i] = tok.replace(stripped, stripped + "확인", 1)
            return " ".join(tokens)
    raise AssertionError("숫자 없는 단어가 하나도 없는 text — 통합 테스트 재료 보정 필요")


# ───────── v2 PASSED (녹화 bd573dd9…) ─────────


def test_verify_v2_passed_through_recorded(
    integration_client: TestClient,
    db_session: Session,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v2")
    get_settings.cache_clear()
    draft = _create_draft(integration_client, draft_request_sample, "DRF-V-PASS")
    res = integration_client.post(
        "/v1/str/verify", json=_verify_body(draft), headers={"X-Internal-Key": INTERNAL_KEY}
    )
    assert res.status_code == 200, res.text
    out = VerifyResponse.model_validate(res.json())
    assert out.status is VerifyStatus.PASSED
    assert out.passed is True
    assert out.llm_checks is not None and len(out.llm_checks) == 5
    assert all(c.score >= 4 for c in out.llm_checks)
    assert out.narrative_refs is not None and len(out.narrative_refs) == 7
    for ref in out.narrative_refs:
        assert set(ref.evidence_ids) <= {1, 2, 3}
    assert out.judge_meta is not None and out.judge_meta.prompt_version == "judge_v2"
    assert out.verifier_version.endswith("+judge_v2")
    row = db_session.execute(
        text(
            "SELECT status, judge_llm_model, judge_tokens_in, judge_tokens_out, "
            "judge_latency_ms, judge_attempts FROM ai.verification_runs "
            "WHERE generation_id=:g"
        ),
        {"g": draft.generation_id},
    ).one()
    assert row.status == "PASSED"
    assert row.judge_attempts == 1
    assert row.judge_llm_model and row.judge_tokens_in is not None


# ───────── v1 LLM_FAILED (녹화 6eefc9f4…, FIVE_W=3) ─────────


def test_verify_v1_llm_failed_through_recorded(
    integration_client: TestClient,
    db_session: Session,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v1 녹화 본문 — 평가자 FIVE_W 3점이라 LLM_FAILED. narrative_refs 는 값 있음."""
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v1")
    get_settings.cache_clear()
    draft = _create_draft(integration_client, draft_request_sample, "DRF-V-LLMF")
    res = integration_client.post(
        "/v1/str/verify", json=_verify_body(draft), headers={"X-Internal-Key": INTERNAL_KEY}
    )
    assert res.status_code == 200, res.text
    out = VerifyResponse.model_validate(res.json())
    assert out.status is VerifyStatus.LLM_FAILED
    assert out.passed is False
    assert out.llm_checks is not None and len(out.llm_checks) == 5
    scored = {c.check.value: c.score for c in out.llm_checks}
    assert scored["FIVE_W_ONE_H_COMPLETE"] == 3  # 녹화 결과 그대로
    assert out.narrative_refs is not None and len(out.narrative_refs) == 6
    assert out.judge_meta is not None and out.judge_meta.prompt_version == "judge_v2"
    row = db_session.execute(
        text("SELECT status, judge_attempts FROM ai.verification_runs WHERE generation_id=:g"),
        {"g": draft.generation_id},
    ).one()
    assert row.status == "LLM_FAILED"


# ───────── CODE_FAILED (v1·v2 각각) ─────────


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
    draft = _create_draft(integration_client, draft_request_sample, draft_id)
    narrative = [s.model_dump(mode="json") for s in draft.narrative]
    narrative[0]["evidence_ids"] = [9999]  # scope = {1,2,3} 밖
    res = integration_client.post(
        "/v1/str/verify",
        json=_verify_body(draft, narrative),
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
    [("narrative_v1", "DRF-V-UNAV1"), ("narrative_v2", "DRF-V-UNAV2")],
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
    draft = _create_draft(integration_client, draft_request_sample, draft_id)
    narrative = [s.model_dump(mode="json") for s in draft.narrative]
    narrative[-1]["text"] = _replace_non_digit_word(narrative[-1]["text"])
    res = integration_client.post(
        "/v1/str/verify",
        json=_verify_body(draft, narrative),
        headers={"X-Internal-Key": INTERNAL_KEY},
    )
    assert res.status_code == 200, res.text
    out = VerifyResponse.model_validate(res.json())
    assert out.status is VerifyStatus.VERIFY_UNAVAILABLE
    assert out.llm_checks is None
    assert out.narrative_refs is None
    assert out.judge_meta is None  # LlmUnavailable 은 토큰 안 씀
