"""str/06 "본문 해시" + str/08 "계약" 층 — narrative_sha256 테스트 벡터.

벡터는 Python 이 기준 (shared/01). W3 에 Java NarrativeHash 가 같은 값을 내야 한다.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from aml_ai.shared.hashing import narrative_sha256
from aml_ai.shared.schemas.str import NarrativeSection

VECTOR_PATH = Path(__file__).resolve().parents[2] / "contracts" / "examples" / "narrative_hash.json"


def _sections(raw: list[dict]) -> list[NarrativeSection]:
    return [NarrativeSection.model_validate(d) for d in raw]


@pytest.fixture
def vector() -> dict:
    return json.loads(VECTOR_PATH.read_text(encoding="utf-8"))


def test_vector_contains_nfd_characters(vector: dict) -> None:
    """벡터가 NFD 문자(한 섹션 이상)를 포함 — 정규화 분기가 실제로 돈다는 보장."""
    nfd_sections = [
        s["section"] for s in vector["narrative"] if unicodedata.normalize("NFC", s["text"]) != s["text"]
    ]
    assert nfd_sections, (
        "벡터에 NFD 문자가 하나도 없음 — NFC 정규화를 안 거쳐도 같은 해시가 나와 테스트 의미 없음"
    )


def test_vector_hash_matches(vector: dict) -> None:
    """계약 — contracts/examples/narrative_hash.json 의 sha256 과 일치."""
    assert narrative_sha256(_sections(vector["narrative"])) == vector["sha256"]


def test_input_order_does_not_change_hash(vector: dict) -> None:
    """입력 순서가 섞여도 같은 해시 — hashing 이 섹션 고정 순서로 정렬."""
    reordered = list(reversed(vector["narrative"]))
    assert narrative_sha256(_sections(reordered)) == vector["sha256"]


def test_cites_and_evidence_ids_ignored(vector: dict) -> None:
    """cites · evidence_ids 를 바꿔도 같은 해시 — section · text 만 들어간다."""
    mutated = [
        {**sec, "cites": ["bogus.key"], "evidence_ids": [999999, 888888]} for sec in vector["narrative"]
    ]
    assert narrative_sha256(_sections(mutated)) == vector["sha256"]


def test_nfd_and_nfc_same_hash(vector: dict) -> None:
    """조합형 자모(NFD) ↔ 완성형(NFC) 같은 해시 — NFC 정규화가 섹션 text 에 적용."""
    nfc = [{**sec, "text": unicodedata.normalize("NFC", sec["text"])} for sec in vector["narrative"]]
    nfd = [{**sec, "text": unicodedata.normalize("NFD", sec["text"])} for sec in vector["narrative"]]
    assert narrative_sha256(_sections(nfc)) == vector["sha256"]
    assert narrative_sha256(_sections(nfd)) == vector["sha256"]


def test_trailing_space_changes_hash(vector: dict) -> None:
    """앞뒤 공백은 자르지 않는다 — 공백 하나 차이면 다른 해시."""
    first = dict(vector["narrative"][0])
    mutated = [{**first, "text": first["text"] + " "}, *vector["narrative"][1:]]
    assert narrative_sha256(_sections(mutated)) != vector["sha256"]


def test_section_count_too_few_raises(vector: dict) -> None:
    """섹션 5개 → ValueError. 메시지에 섹션 이름·개수만, text 는 없음(로그 금지 규칙)."""
    five = vector["narrative"][:5]
    with pytest.raises(ValueError) as exc:
        narrative_sha256(_sections(five))
    _assert_text_not_leaked(str(exc.value), vector)


def test_section_count_too_many_raises(vector: dict) -> None:
    """섹션 7개(아무 섹션 중복) → ValueError."""
    seven = [*vector["narrative"], vector["narrative"][0]]
    with pytest.raises(ValueError) as exc:
        narrative_sha256(_sections(seven))
    _assert_text_not_leaked(str(exc.value), vector)


def test_section_duplicate_raises(vector: dict) -> None:
    """len=6 이지만 하나 누락 + 하나 중복 → ValueError."""
    duplicated = [{**vector["narrative"][0]} for _ in range(2)] + vector["narrative"][2:]
    assert len(duplicated) == 6
    with pytest.raises(ValueError) as exc:
        narrative_sha256(_sections(duplicated))
    _assert_text_not_leaked(str(exc.value), vector)


@pytest.mark.parametrize("blank", [" ", "   ", "\n\t ", "　"])
def test_whitespace_only_text_rejected_by_schema(vector: dict, blank: str) -> None:
    """strip off 영향 — 공백·탭·개행·전각공백만 text 는 NarrativeSection 이 거부(해시까지 가지 않음)."""
    mutated = [{**vector["narrative"][0], "text": blank}, *vector["narrative"][1:]]
    with pytest.raises(ValueError):
        _sections(mutated)


def _assert_text_not_leaked(message: str, vector: dict) -> None:
    for sec in vector["narrative"]:
        assert sec["text"].strip() not in message, "오류 메시지에 narrative text 가 섞여 들어감"
