"""`/v1/cases/ask` HTTP → DB — 상태 4종 각각 저장 행 (SCRUM-290 2/2, 08 "HTTP→DB 4").

흐름 — HTTP → AskService → ops 읽기(fan_in 시드) → facts → end_read → 녹화 재생(계획·답) → 검사 → generations(kind=ASK).
ANSWERED = F1 녹화(계획 v2·답 v4 — SCRUM-362 추가 검토 1: DB 로 만든 facts 도 같은 녹화 키) · OUT_OF_SCOPE = O3 녹화 ·
NO_DATA·UNVERIFIED = F1 계획 녹화 + 답만 고정 원문(`FixedAnswer`, v4 모양). `recorded/` 는 실제 출력만.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from aml_ai.shared.config import get_settings
from aml_ai.shared.schemas.str import AskResponse
from tests.conftest import EXAMPLES, load_json
from tests.str.ask_recorded_support import FixedAnswer, item, recorded
from tests.str.integration_support import INTEGRATION_INTERNAL_KEY

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db
NOT_ANSWERABLE = object()  # answerable false


def _body(question: str, case_no: str) -> dict:
    """ops_seed 가 가정하는 fan_in 요청 — 요약 통합 테스트와 같은 숫자."""
    body = load_json(EXAMPLES / "ask_request.json")
    body["case_no"] = case_no
    body["alert"] = {
        **body["alert"],
        "account_key": "10_8000EBD30",
        "entity_id": "80062E240",
        "transaction_ids": [1, 2, 3],
    }
    body["evidence_transaction_ids"] = [1, 2, 3]
    body["question"] = question
    return body


@pytest.mark.parametrize(
    "state, item_id, edit",
    [
        ("ANSWERED", "F1", None),  # 추가 검토 1 — 계획 v2·답 v4 녹화 그대로
        ("OUT_OF_SCOPE", "O3", None),
        ("NO_DATA", "F1", NOT_ANSWERABLE),
        ("UNVERIFIED", "F1", "입금 거래는 모두 5건이에요."),
    ],
    ids=["answered", "out_of_scope", "no_data", "unverified"],
)
def test_ask_state_through_http_and_saved_row(
    state: str,
    item_id: str,
    edit,
    integration_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_settings.cache_clear()
    if edit is not None:
        import aml_ai.str.application.ask_service as mod

        answer = None if edit is NOT_ANSWERABLE else edit
        monkeypatch.setattr(mod, "make_llm_client", lambda _s: FixedAnswer(recorded(), answer))
    body = _body(item(item_id)["question"], f"CASE-ASK-{state}")
    res = integration_client.post(
        "/v1/cases/ask", json=body, headers={"X-Internal-Key": INTEGRATION_INTERNAL_KEY}
    )
    assert res.status_code == 200, res.text
    out = AskResponse.model_validate(res.json())
    assert out.status.value == state
    row = db_session.execute(
        text(
            "SELECT kind, status, draft_id, response->>'status' AS rs, response->'llm_answer' AS la "
            "FROM ai.generations WHERE case_no=:c"
        ),
        {"c": body["case_no"]},
    ).one()
    assert (row.kind, row.status, row.draft_id, row.rs) == ("ASK", "SUCCEEDED", None, state)
    assert (row.la is None) is (state == "OUT_OF_SCOPE")
    if state == "ANSWERED":  # 렌더링한 답(자리표 없음) · cites = 자리표 키 · 저장 행 원문은 자리표 그대로
        assert "{{" not in out.answer and out.cites and "{{" in row.la["answer"]
