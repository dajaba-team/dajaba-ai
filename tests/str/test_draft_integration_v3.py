"""SCRUM-225 — narrative_v3 녹화(42c985cb6b2e2770, RAG 끔) 재생 초안의 코드 검사.

알려진 검사기 오판 1건을 그대로 단언한다(docs/str/09 SCRUM-225 동결 줄): PLACE "상대 계좌는 3개이며
자행 계좌는 0개" 에서 총수 3 을 최근접 "자행" 에 붙여 자행 수(0)로 읽음 → COUNT_MATCH MISMATCH.
SCRUM-131 에서 검사기를 고치면 이 단언을 "불일치 0" 으로 바꾼다. 그 밖의 불일치는 0 이어야 한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import DraftResponse
from aml_ai.str.domain.verification import run_code_checks
from tests.str.integration_support import INTEGRATION_INTERNAL_KEY
from tests.str.test_draft_integration import _fan_in_body

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

pytestmark = pytest.mark.db


def test_v3_recorded_draft_code_checks_only_known_place_misread(
    integration_client: TestClient,
    draft_request_sample: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NARRATIVE_PROMPT", "narrative_v3")
    get_settings.cache_clear()
    body = _fan_in_body(draft_request_sample, draft_id="DRF-V3-CODECHECK")
    res = integration_client.post(
        "/v1/str/drafts", json=body, headers={"X-Internal-Key": INTEGRATION_INTERNAL_KEY}
    )
    assert res.status_code == 200, res.text
    out = DraftResponse.model_validate(res.json())
    assert out.generation_meta.prompt_version == "narrative_v3"
    assert out.generation_meta.references == []  # RAG 끔 — 녹화 전제
    checks = run_code_checks(out.facts, out.narrative, [1, 2, 3])
    mismatches = [
        (c.check.value, c.section.value if c.section else None, c.draft_value, c.source_value)
        for c in checks
        if not c.match
    ]
    assert mismatches == [("COUNT_MATCH", "PLACE", "3개", "{0}")]
