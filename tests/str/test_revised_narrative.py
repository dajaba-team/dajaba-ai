"""수정본 섹션 5,000자 NFC·UTF-16 — 규약 §5.3·docs/str/06·09_decisions 10/30 미결 24. SCRUM-46.

경계 테스트 9개 (지시서 9번):
  1 5,000자 통과 · 2 5,001자 거부 · 3 "4,999자 + 😀" 거부(5,001로 셈)
  4 NFD 한글 5,000자 통과(코드포인트 >5,000) · 5 요청 text 변경 없음 + 해시 NFD↔NFC 동일
  6 1,201~5,000자 수정본 통과(SCRUM-46 전엔 막혔음, 회귀 방지)
  7 생성 쪽 LlmNarrativeSection 은 여전히 1,200자에서 막힘
  8 DraftResponse.narrative 도 1,200자에서 막힘
  9 공백만 text 는 NarrativeSection·RevisedNarrativeSection 둘 다 거부(기존 동작)

세기 함수·validator 본문·`VerifyRequest.narrative` 타입 교체는 Codex 구현(/codex:rescue).
테스트 파일은 Codex 가 수정하지 않는다.
"""

from __future__ import annotations

import unicodedata
from copy import deepcopy

import pytest
from pydantic import ValidationError

from aml_ai.shared.hashing import narrative_sha256
from aml_ai.shared.schemas.str import (
    DraftResponse,
    LlmNarrativeSection,
    NarrativeOut,
    NarrativeSection,
    RevisedNarrativeSection,
    SectionV1,
    VerifyRequest,
)
from tests.conftest import EXAMPLES, load_json

# "가" NFC = 1 code point, UTF-16 1 unit. NFD = "ᄀ"+"ᅡ" = 2 code points, UTF-16 2 units → NFC 뒤 1.
NFC_CHAR = "가"
NFD_CHAR = unicodedata.normalize("NFD", "가")  # len=2 in Python
EMOJI = "😀"  # U+1F600, BMP 밖 — Python len=1, UTF-16 2 units, Java String.length()=2


def _verify_request_with_text(section: SectionV1, text: str) -> dict:
    """verify_request.json 을 복제하고 한 섹션의 text 를 바꾼다."""
    d = deepcopy(load_json(EXAMPLES / "verify_request.json"))
    for s in d["narrative"]:
        if s["section"] == section.value:
            s["text"] = text
            return d
    raise AssertionError(f"section {section} not in example")


# ---------- 1. 5,000자 통과 ----------
def test_revised_5000_passes() -> None:
    d = _verify_request_with_text(SectionV1.SUMMARY, NFC_CHAR * 5000)
    VerifyRequest.model_validate(d)


# ---------- 2. 5,001자 거부 ----------
def test_revised_5001_rejected() -> None:
    d = _verify_request_with_text(SectionV1.SUMMARY, NFC_CHAR * 5001)
    with pytest.raises(ValidationError):
        VerifyRequest.model_validate(d)


# ---------- 3. "4,999자 + 😀" 거부 (UTF-16 으로 5,001) ----------
def test_revised_4999_plus_emoji_rejected() -> None:
    d = _verify_request_with_text(SectionV1.SUMMARY, NFC_CHAR * 4999 + EMOJI)
    with pytest.raises(ValidationError):
        VerifyRequest.model_validate(d)


# ---------- 4. NFD 한글 5,000자(코드포인트 10,000) 통과 ----------
def test_revised_nfd_hangul_5000_passes() -> None:
    text = NFD_CHAR * 5000  # 10,000 code points → NFC 뒤 5,000 UTF-16 단위
    d = _verify_request_with_text(SectionV1.SUMMARY, text)
    VerifyRequest.model_validate(d)


# ---------- 5. 요청 text 는 바뀌지 않고, 해시가 NFD/NFC 동일 ----------
def test_revised_nfd_text_unchanged_and_hash_matches_nfc() -> None:
    text_nfd = NFD_CHAR * 10 + "힇"  # mixed
    nfd_req = VerifyRequest.model_validate(_verify_request_with_text(SectionV1.SUMMARY, text_nfd))
    summary = next(s for s in nfd_req.narrative if s.section is SectionV1.SUMMARY)
    assert summary.text == text_nfd, "검증 요청 text 가 변하면 해시가 Java 와 어긋남"

    text_nfc = unicodedata.normalize("NFC", text_nfd)
    nfc_req = VerifyRequest.model_validate(_verify_request_with_text(SectionV1.SUMMARY, text_nfc))
    assert narrative_sha256(nfd_req.narrative) == narrative_sha256(nfc_req.narrative)


# ---------- 6. 1,201 ~ 5,000자 통과 (회귀 방지) ----------
@pytest.mark.parametrize("n", [1201, 2500, 5000])
def test_revised_middle_range_passes(n: int) -> None:
    d = _verify_request_with_text(SectionV1.SUMMARY, NFC_CHAR * n)
    VerifyRequest.model_validate(d)


# ---------- 7. LLM 출력(NarrativeOut) 1,201자 거부 ----------
def test_llm_narrative_still_1200_cap() -> None:
    with pytest.raises(ValidationError):
        LlmNarrativeSection.model_validate({"section": "SUMMARY", "text": NFC_CHAR * 1201, "cites": []})
    # NarrativeOut 전체로도 같은 경로
    d = {
        "narrative": [
            {"section": s.value, "text": NFC_CHAR * (1201 if s is SectionV1.SUMMARY else 10), "cites": []}
            for s in SectionV1
        ]
    }
    with pytest.raises(ValidationError):
        NarrativeOut.model_validate(d)


# ---------- 8. DraftResponse.narrative 도 1,200자에서 막힘 ----------
def test_draft_response_still_1200_cap() -> None:
    d = deepcopy(load_json(EXAMPLES / "draft_response.json"))
    d["narrative"][0]["text"] = NFC_CHAR * 1201
    with pytest.raises(ValidationError):
        DraftResponse.model_validate(d)


# ---------- 9. 공백만 text — 두 섹션 타입 다 거부 ----------
@pytest.mark.parametrize("blank", [" ", "   ", "\n\t ", "　"])
def test_whitespace_only_rejected_by_both_section_types(blank: str) -> None:
    with pytest.raises(ValidationError):
        RevisedNarrativeSection.model_validate(
            {"section": "SUMMARY", "text": blank, "cites": [], "evidence_ids": []}
        )
    with pytest.raises(ValidationError):
        NarrativeSection.model_validate(
            {"section": "SUMMARY", "text": blank, "cites": [], "evidence_ids": []}
        )
