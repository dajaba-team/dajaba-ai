"""v2 PASSED·LLM_FAILED 경로 — judge_v3 녹화 PASSED + judge_v2 녹화 LLM_FAILED 기록용.

SCRUM-61 당시 PASSED 였던 자리 → SCRUM-140(11/7) narrative v2 재녹화 2회 모두 OPINION·METHOD 반복으로
judge_v2 녹화가 FIVE_W=3 → LLM_FAILED 였음. SCRUM-127(2026-11-09) 로 judge_v3(06 표 4칸 루브릭) 로
교체하자 같은 v2 본문이 FIVE_W=5·TYPO=5·… = **PASSED** 로 통과. `test_verify_v2_passed_through_recorded`
는 judge_v3 녹화로 복구. judge_v2 녹화는 "4점 칸 없던 프롬프트의 자연 실패" 기록용으로
`test_verify_v2_llm_failed_through_recorded_judge_v2_history` 로 남김(SCRUM-127 PR 본문 근거 재생).
"""

from __future__ import annotations

import json
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


def test_verify_v2_passed_through_recorded(
    integration_client: TestClient,
    db_session: Session,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v2 녹화 — judge_v3 (SCRUM-127, 4칸 루브릭) 로 전부 ≥4 → PASSED. SCRUM-61 복구, SCRUM-140 보류 해제."""
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v2")
    get_settings.cache_clear()
    draft = create_draft(integration_client, draft_request_sample, "DRF-V-PASS2")
    res = integration_client.post(
        "/v1/str/verify", json=verify_body(draft), headers={"X-Internal-Key": INTERNAL_KEY}
    )
    assert res.status_code == 200, res.text
    out = VerifyResponse.model_validate(res.json())
    assert out.status is VerifyStatus.PASSED and out.passed is True
    assert out.llm_checks is not None and len(out.llm_checks) == 5
    assert all(c.score >= 4 for c in out.llm_checks)
    assert out.narrative_refs is not None and len(out.narrative_refs) == 7
    assert all(set(ref.evidence_ids) <= {1, 2, 3} for ref in out.narrative_refs)
    assert out.judge_meta is not None and out.judge_meta.prompt_version == "judge_v3"
    assert out.verifier_version.endswith("+judge_v3")
    row = db_session.execute(
        text(
            "SELECT status, judge_llm_model, judge_tokens_in, judge_attempts"
            " FROM ai.verification_runs WHERE generation_id=:g"
        ),
        {"g": draft.generation_id},
    ).one()
    # SCRUM-207 — verify 경로 N 중앙값(JUDGE_VOTES=3) 이라 녹화 재생 3회 submit → attempts=3
    assert row.status == "PASSED" and row.judge_attempts == 3
    assert row.judge_llm_model and row.judge_tokens_in is not None


def test_verify_v2_llm_failed_through_recorded_judge_v2_history() -> None:
    """judge_v2 녹화(`382bdb46…`) 를 기록용으로 유지 — SCRUM-127 근거 재생.

    04 표 "4점 칸 없던 프롬프트가 4점 범위 본문을 3점으로 떨어뜨렸다" 의 자연 실패 사례.
    verify 통합은 `JUDGE_PROMPT=judge_v3` 라 judge_v2 녹화를 안 쓰지만, 녹화 파일 자체와 점수는 보존.
    """
    from pathlib import Path

    rec = Path(__file__).resolve().parents[1] / "str/recorded/judge_v2/382bdb46f14e94fc.json"
    assert rec.exists(), f"SCRUM-140 녹화 보존 — {rec} 지우지 말 것"
    inner = json.loads(json.loads(rec.read_text())["text"])
    scores = {c["check"]: c["score"] for c in inner["checks"]}
    assert scores["FIVE_W_ONE_H_COMPLETE"] == 3, f"기록용: v2 본문 FIVE_W=3 유지 확인 — {scores}"
    assert min(scores.values()) == 3, f"min=3 (LLM_FAILED) 기록 유지 — {scores}"
