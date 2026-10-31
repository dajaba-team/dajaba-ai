"""`/v1/str/drafts` 녹화 통합 테스트 (SCRUM-20).

흐름 — HTTP → DraftService → 선점 → ops 읽기 → facts → 마스킹 → few-shot → RecordedLlmClient
→ attach_evidence → 펜싱 저장 → 응답. `AI_LLM_MOCK=true`·`RAG_ENABLED=false`.
`NARRATIVE_PROMPT` 를 `narrative_v1`·`narrative_v2` 둘 다 파라미터.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import DraftResponse, Facts
from tests.str.conftest import INTEGRATION_INTERNAL_KEY

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_FAN_IN = REPO_ROOT / "tests" / "str" / "fixtures" / "facts_fan_in.json"
INTERNAL_KEY = INTEGRATION_INTERNAL_KEY


def _fan_in_body(sample: dict, *, draft_id: str = "DRF-SCRUM20-01", notes_extra: str = "") -> dict:
    """ops_seed 와 fixture 가 가정하는 요청 모양.

    `tools.record._build_prompt` 가 `notes=None` 으로 조립하므로, 녹화 재생이 매칭되려면
    통합 테스트 요청도 `investigator_notes=None` (또는 miss 유도용 추가 문자열만).
    """
    body = {**sample}
    body["draft_id"] = draft_id
    body["alert"] = {
        **body["alert"],
        "account_key": "010_8000EBD30",
        "entity_id": "80062E240",
        "transaction_ids": [1, 2, 3],
    }
    body["evidence_transaction_ids"] = [1, 2, 3]
    body["investigator_notes"] = notes_extra or None
    return body


# 선행 facts == fixture 는 `test_draft_integration_seed.py` 로 분리(200줄 관문).


# ───────── 정상 ─────────


@pytest.mark.parametrize(
    ("prompt_name", "section_count"),
    [("narrative_v1", 6), ("narrative_v2", 7)],
)
def test_draft_success_through_recorded_llm(
    integration_client: TestClient,
    db_session: Session,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
    prompt_name: str,
    section_count: int,
) -> None:
    """200 + facts == fixture + 섹션 수 + prompt_version + generations SUCCEEDED."""
    monkeypatch.setenv("NARRATIVE_PROMPT", prompt_name)
    get_settings.cache_clear()
    body = _fan_in_body(draft_request_sample, draft_id=f"DRF-OK-{prompt_name}")
    res = integration_client.post("/v1/str/drafts", json=body, headers={"X-Internal-Key": INTERNAL_KEY})
    assert res.status_code == 200, res.text
    out = DraftResponse.model_validate(res.json())
    assert out.verification is None
    assert out.generation_meta.prompt_version == prompt_name
    assert len(out.narrative) == section_count
    for s in out.narrative:
        assert set(s.evidence_ids) <= {1, 2, 3}, "evidence_ids ⊆ 요청 evidence_transaction_ids"
    fixture_facts = Facts.model_validate(json.loads(FIXTURE_FAN_IN.read_text(encoding="utf-8")))
    assert out.facts.model_dump(mode="json") == fixture_facts.model_dump(mode="json")
    row = db_session.execute(
        text("SELECT status FROM ai.generations WHERE draft_id=:d"), {"d": body["draft_id"]}
    ).one()
    assert row.status == "SUCCEEDED"


# ───────── 경계 — 같은 draft_id·같은 본문 재요청: ClaimReuse ─────────


def test_same_draft_same_body_returns_claim_reuse(
    integration_client: TestClient,
    db_session: Session,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """같은 요청 두 번 → 두 번째는 저장 결과 그대로. generations 행 1개."""
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v1")
    get_settings.cache_clear()
    body = _fan_in_body(draft_request_sample, draft_id="DRF-REUSE-01")
    first = integration_client.post("/v1/str/drafts", json=body, headers={"X-Internal-Key": INTERNAL_KEY})
    second = integration_client.post("/v1/str/drafts", json=body, headers={"X-Internal-Key": INTERNAL_KEY})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["generation_id"] == second.json()["generation_id"]
    count = db_session.execute(
        text("SELECT COUNT(*) FROM ai.generations WHERE draft_id=:d"), {"d": body["draft_id"]}
    ).scalar_one()
    assert count == 1


# ───────── 실패 ─────────


# ───────── 실패 — `test_draft_integration_errors.py` 로 분리(200줄 관문)
