"""섹션 enum 두 집합 공존 (SCRUM-47) — v2 스키마 수용·거부, LLM 출력 enum 분리, OPINION_PRESENT.

v1 회귀는 기존 `test_hashing.py`·`test_schemas.py`·`test_record_matches_service.py` 가 커버.
v2 해시 벡터·순서 섞임은 `test_hashing_v2.py`.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import (
    CheckReason,
    CodeCheckName,
    LlmNarrativeSection,
    NarrativeOut,
    NarrativeOutV1,
    NarrativeOutV2,
    NarrativeSection,
    SectionV1,
    SectionV2,
)
from aml_ai.str.domain.verification import opinion_present


def _v2_sections_payload() -> list[dict]:
    """7개 유효 섹션 — 테스트에서 반복 사용."""
    return [
        {"section": "SUBJECT", "text": "대상자.", "cites": []},
        {"section": "DATE", "text": "2022-09-02 00:14 ~ 22:51.", "cites": []},
        {"section": "PLACE", "text": "포르투갈 은행.", "cites": []},
        {"section": "INSTRUMENT", "text": "ACH.", "cites": []},
        {"section": "METHOD", "text": "집중 입금.", "cites": []},
        {"section": "GROUNDS", "text": "관측값(24h 기준) 상대 수 31개.", "cites": []},
        {"section": "OPINION", "text": "추가 확인 필요.", "cites": []},
    ]


def _v1_sections_payload() -> list[dict]:
    return [
        {"section": "SUMMARY", "text": "요약.", "cites": []},
        {"section": "WHO", "text": "대상자.", "cites": []},
        {"section": "WHAT_WHEN_WHERE", "text": "기간.", "cites": []},
        {"section": "HOW", "text": "방식.", "cites": []},
        {"section": "WHY_SUSPICIOUS", "text": "사유.", "cites": []},
        {"section": "CONCLUSION", "text": "결론.", "cites": []},
    ]


# ---------- NarrativeOut (공용 스키마) ----------


def test_narrative_out_accepts_v2_full_set() -> None:
    assert len(NarrativeOut.model_validate({"narrative": _v2_sections_payload()}).narrative) == 7


def test_narrative_out_accepts_v1_full_set() -> None:
    """v1 6개 집합을 그대로 받는다(회귀)."""
    assert len(NarrativeOut.model_validate({"narrative": _v1_sections_payload()}).narrative) == 6


def test_narrative_out_rejects_mixed_v1_v2() -> None:
    """v1 5개 + v2 1개 섞음 → 거부(`_each_section_once` 가 집합 거부)."""
    mixed = _v1_sections_payload()[:5] + [{"section": "OPINION", "text": "의견.", "cites": []}]
    with pytest.raises(ValueError):
        NarrativeOut.model_validate({"narrative": mixed})


def test_narrative_out_rejects_v2_duplicate() -> None:
    dup = _v2_sections_payload()
    dup.append(dup[0])
    with pytest.raises(ValueError):
        NarrativeOut.model_validate({"narrative": dup})


def test_narrative_out_rejects_v2_missing() -> None:
    """v2 6개(OPINION 빠짐) → 거부(v1 집합도 아니므로)."""
    with pytest.raises(ValueError):
        NarrativeOut.model_validate({"narrative": _v2_sections_payload()[:6]})


# ---------- LLM 출력 스키마 (버전별) ----------


def test_llm_output_v1_schema_only_shows_v1_enum() -> None:
    """NarrativeOutV1 JSON Schema 는 v1 enum 6개만 노출."""
    assert set(_extract_section_enum(NarrativeOutV1.model_json_schema())) == {e.value for e in SectionV1}


def test_llm_output_v2_schema_only_shows_v2_enum() -> None:
    assert set(_extract_section_enum(NarrativeOutV2.model_json_schema())) == {e.value for e in SectionV2}


def test_llm_output_v1_rejects_v2_section_name() -> None:
    with pytest.raises(ValueError):
        NarrativeOutV1.model_validate({"narrative": _v2_sections_payload()})


def test_llm_output_v2_rejects_v1_section_name() -> None:
    with pytest.raises(ValueError):
        NarrativeOutV2.model_validate({"narrative": _v1_sections_payload()})


# ---------- OPINION_PRESENT ----------


@pytest.mark.parametrize("blank_text", ["자료 없음", "해당 없음", "없음", "-", " 자료 없음  ", "자료 없음\n"])
def test_opinion_present_fails_on_blank_phrases(blank_text: str) -> None:
    """v2 OPINION 이 공란 표현(strip·NFC 뒤)이면 reason=MISSING."""
    payload = _v2_sections_payload()
    payload[-1]["text"] = blank_text
    checks = opinion_present([NarrativeSection.model_validate(d) for d in payload])
    assert len(checks) == 1
    assert checks[0].check is CodeCheckName.OPINION_PRESENT
    assert checks[0].match is False and checks[0].reason is CheckReason.MISSING


def test_opinion_present_passes_on_real_opinion_text() -> None:
    sections = [NarrativeSection.model_validate(d) for d in _v2_sections_payload()]
    checks = opinion_present(sections)
    assert len(checks) == 1 and checks[0].match is True and checks[0].reason is None


def test_opinion_present_not_applied_to_v1() -> None:
    """v1 집합에는 안 돈다 — 빈 결과."""
    sections = [NarrativeSection.model_validate(d) for d in _v1_sections_payload()]
    assert opinion_present(sections) == []


# ---------- LLM 섹션 — v1/v2 자동 분기 ----------


def test_llm_narrative_section_resolves_v2_name() -> None:
    """공용 `LlmNarrativeSection` 은 str 입력을 SectionV1·V2 중 매칭되는 enum 으로 자동 변환."""
    section = LlmNarrativeSection.model_validate({"section": "OPINION", "text": "결론."})
    assert section.section == SectionV2.OPINION


# ---------- helper ----------


def _extract_section_enum(schema: dict) -> list[str]:
    """JSON schema 전체에서 `section` 필드의 enum 또는 참조된 `$defs` enum 을 찾는다."""
    defs = schema.get("$defs", {})

    def walk(node) -> list[str] | None:
        if isinstance(node, dict):
            if "properties" in node and "section" in node["properties"]:
                sec = node["properties"]["section"]
                if "enum" in sec:
                    return sec["enum"]
                if "$ref" in sec:
                    return defs[sec["$ref"].split("/")[-1]]["enum"]
            for v in node.values():
                found = walk(v)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found:
                    return found
        return None

    return walk(schema) or []
