"""narrative 해시 v2 (SCRUM-47) — 집합 보고 순서 선택, 벡터 일치, 순서 섞어도 같은 값.

v1 벡터·회귀는 `test_hashing.py` 가 커버. 이 파일은 v2 7섹션 추가분.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aml_ai.shared.hashing import narrative_sha256
from aml_ai.shared.schemas.str import NarrativeSection

V2_VECTOR_PATH = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "narrative_hash_v2.json"


@pytest.fixture
def v2_vector() -> dict:
    return json.loads(V2_VECTOR_PATH.read_text(encoding="utf-8"))


def _sections(raw: list[dict]) -> list[NarrativeSection]:
    return [NarrativeSection.model_validate(d) for d in raw]


def test_v2_vector_hash_matches(v2_vector: dict) -> None:
    """계약 — narrative_hash_v2.json 의 sha256 과 일치(Python 기준값)."""
    assert narrative_sha256(_sections(v2_vector["narrative"])) == v2_vector["sha256"]


def test_v2_hash_order_independent(v2_vector: dict) -> None:
    """입력 순서가 섞여도 같은 해시 — 집합 보고 v2 순서로 정렬."""
    assert narrative_sha256(_sections(reversed(v2_vector["narrative"]))) == v2_vector["sha256"]


def test_hash_rejects_mixed_section_set() -> None:
    """v1 5개 + v2 1개 섞인 입력 → ValueError."""
    mixed = [
        {"section": "SUMMARY", "text": "요약.", "cites": []},
        {"section": "WHO", "text": "대상자.", "cites": []},
        {"section": "WHAT_WHEN_WHERE", "text": "기간.", "cites": []},
        {"section": "HOW", "text": "방식.", "cites": []},
        {"section": "WHY_SUSPICIOUS", "text": "사유.", "cites": []},
        {"section": "OPINION", "text": "의견.", "cites": []},
    ]
    with pytest.raises(ValueError):
        narrative_sha256(_sections(mixed))
