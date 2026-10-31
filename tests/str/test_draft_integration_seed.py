"""ops_seed → 서비스 facts == `facts_fan_in.json` 선행 테스트 (SCRUM-20).

녹화 전에 반드시 녹색이어야 한다 — 서비스 조립이 fixture 와 다르면 녹화 키가 깨져 재생이
LlmUnavailable 로 돌아감(SCRUM-47 Codex 1차와 같은 유형). 여기서 먼저 잡음.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aml_ai.shared.schemas.str import DraftRequest, Facts
from aml_ai.str.domain import facts as facts_domain
from aml_ai.str.infrastructure.transaction_reader import TransactionReader

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_FAN_IN = REPO_ROOT / "tests" / "str" / "fixtures" / "facts_fan_in.json"


def _fan_in_request(sample: dict) -> DraftRequest:
    body = {**sample}
    body["alert"] = {
        **body["alert"],
        "account_key": "010_8000EBD30",
        "entity_id": "80062E240",
        "transaction_ids": [1, 2, 3],
    }
    body["evidence_transaction_ids"] = [1, 2, 3]
    body["investigator_notes"] = None
    return DraftRequest.model_validate(body)


def test_ops_seed_facts_match_fixture(
    _ops_seed: None, db_session: Session, draft_request_sample: dict
) -> None:
    """ops_seed 로 서비스가 계산한 facts == `facts_fan_in.json` (글자 하나 안 다르게)."""
    req = _fan_in_request(draft_request_sample)
    reader = TransactionReader(db_session)
    txs = reader.load_transactions(req.evidence_transaction_ids)
    subject = reader.load_subject(req.alert, txs)
    service_facts = facts_domain.build_facts(req, txs, subject)

    fixture_facts = Facts.model_validate(json.loads(FIXTURE_FAN_IN.read_text(encoding="utf-8")))
    assert service_facts.model_dump(mode="json") == fixture_facts.model_dump(mode="json"), (
        "ops_seed 로 계산한 facts 가 fixture 와 다르다 — 녹화 전에 fixture 또는 seed 를 고치자."
    )
