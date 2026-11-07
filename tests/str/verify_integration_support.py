"""verify 녹화 통합 테스트 공용 — `/v1/str/verify` 두 쌍 테스트 파일이 쓴다 (SCRUM-61·140).

helper 는 작지만 두 파일 모두가 같은 모양을 쓰므로 한 자리로. 테스트 파일별 관문 200 줄 유지.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from aml_ai.shared.schemas.str import DraftResponse
from tests.str.integration_support import INTEGRATION_INTERNAL_KEY

INTERNAL_KEY = INTEGRATION_INTERNAL_KEY


def draft_body(sample: dict, draft_id: str) -> dict:
    body = {**sample}
    body["draft_id"] = draft_id
    body["alert"] = {
        **body["alert"],
        "account_key": "10_8000EBD30",
        "entity_id": "80062E240",
        "transaction_ids": [1, 2, 3],
    }
    body["evidence_transaction_ids"] = [1, 2, 3]
    body["investigator_notes"] = None
    return body


def create_draft(client: TestClient, sample: dict, draft_id: str) -> DraftResponse:
    body = draft_body(sample, draft_id)
    res = client.post("/v1/str/drafts", json=body, headers={"X-Internal-Key": INTERNAL_KEY})
    assert res.status_code == 200, res.text
    return DraftResponse.model_validate(res.json())


def verify_body(draft: DraftResponse, narrative_override: list | None = None) -> dict:
    sections = narrative_override or [s.model_dump(mode="json") for s in draft.narrative]
    return {"generation_id": draft.generation_id, "revision_no": 1, "narrative": sections}


def replace_non_digit_word(text_value: str) -> str:
    """숫자 없는 단어 하나만 다른 글자로 — 코드 검사(금액·날짜·건수·계좌) 영향 없음."""
    tokens = text_value.split()
    for i, tok in enumerate(tokens):
        stripped = tok.strip(".,;:()[]{}")
        if stripped and not any(ch.isdigit() for ch in stripped):
            tokens[i] = tok.replace(stripped, stripped + "확인", 1)
            return " ".join(tokens)
    raise AssertionError("숫자 없는 단어가 하나도 없는 text — 통합 테스트 재료 보정 필요")
