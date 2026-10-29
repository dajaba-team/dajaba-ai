"""contracts/examples/*.json 이 shared/schemas 로 파싱되는지. 백엔드도 같은 파일로 DTO 테스트 (docs/shared/01)."""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.alerts import ScoreRequest
from aml_ai.shared.schemas.errors import ErrorBody
from aml_ai.shared.schemas.scores import ScoreResponse
from aml_ai.shared.schemas.str import DraftRequest, DraftResponse, VerifyRequest, VerifyResponse
from tests.conftest import EXAMPLES, load_json

CASES = [
    ("score_request.json", ScoreRequest),
    ("score_response.json", ScoreResponse),
    ("draft_request.json", DraftRequest),
    ("draft_response.json", DraftResponse),
    ("verify_request.json", VerifyRequest),
    ("verify_response.json", VerifyResponse),
    ("error.json", ErrorBody),
]


@pytest.mark.parametrize(("name", "model"), CASES)
def test_example_parses(name: str, model: type) -> None:
    model.model_validate(load_json(EXAMPLES / name))


UNMAPPED = {"narrative_hash.json"}  # 모델이 아니라 해시 테스트 벡터 — tests/str/test_hashing.py


def test_examples_are_all_listed() -> None:
    files = {p.name for p in EXAMPLES.glob("*.json")} - UNMAPPED
    assert files == {n for n, _ in CASES}, "examples 폴더와 CASES 가 다르다 — README 표도 같이"
