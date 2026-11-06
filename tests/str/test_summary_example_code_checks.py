"""예시 왕복 (SCRUM-129) — summary_request.json 으로 build_facts → summary_response.json 의
summary_lines 를 run_summary_code_checks 돌림 → 결과가 예시 code_checks 와 같은 모양.

예시가 "구현과 같은 숫자" 임을 CI 에서 보장 — 설계 md 와 예시가 어긋나지 않음.
"""

from __future__ import annotations

import json

import pytest

from aml_ai.shared.schemas.str import CodeCheckName, Facts, SummaryRequest, SummaryResponse
from aml_ai.str.domain.verification import run_summary_code_checks
from tests.conftest import EXAMPLES


@pytest.fixture
def req() -> SummaryRequest:
    return SummaryRequest.model_validate(json.loads((EXAMPLES / "summary_request.json").read_text()))


@pytest.fixture
def resp() -> SummaryResponse:
    return SummaryResponse.model_validate(json.loads((EXAMPLES / "summary_response.json").read_text()))


@pytest.fixture
def draft_facts() -> Facts:
    """예시 facts — draft_response.json 과 같은 facts 숫자 분포(SCRUM-129 예시 설계)."""
    data = json.loads((EXAMPLES / "draft_response.json").read_text())
    return Facts.model_validate(data["facts"])


def test_example_summary_lines_all_match(
    req: SummaryRequest, resp: SummaryResponse, draft_facts: Facts
) -> None:
    """예시 summary_lines 가 예시 facts 와 어긋나지 않음 — 4종 전부 match=true."""
    checks = run_summary_code_checks(
        draft_facts, resp.summary_lines, transaction_ids=list(req.evidence_transaction_ids)
    )
    bad = [c for c in checks if c.match is False]
    assert not bad, f"예시 summary_lines 가 facts 와 안 맞음 — code_checks 실패: {bad}"
    # EVIDENCE_IN_SCOPE·OPINION_PRESENT 없음
    names = {c.check for c in checks}
    assert CodeCheckName.EVIDENCE_IN_SCOPE not in names
    assert CodeCheckName.OPINION_PRESENT not in names
