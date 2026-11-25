"""SCRUM-425 참고 사례 관련 구절 `excerpt` — 고르기·자르기(순수) · 스키마 칸 (docs/shared/01 · str/10). DB·LLM 0.

길이 = NFC 뒤 UTF-16 코드 유닛 ≤ 300(백엔드 `String.length()` 와 같은 단위) · 넘으면 299 + `…` · 대리쌍 안 가름.
"""

from __future__ import annotations

import unicodedata

import pytest
from aml_ai.str.domain.reference_excerpt import excerpt_of
from pydantic import ValidationError

from aml_ai.shared.schemas.str import Reference, ReferenceResult
from aml_ai.shared.schemas.str.reference_search import REFERENCE_EXCERPT_MAX
from aml_ai.shared.text import utf16_len_nfc
from aml_ai.str.domain.constants_references import REFERENCE_EXCERPT_ELLIPSIS
from aml_ai.str.domain.reference_search import excerpt_typology
from aml_ai.str.infrastructure.reference_snippet import reference_excerpt

EMOJI = "😀"  # BMP 밖 — UTF-16 2 유닛


def test_constants_follow_contract() -> None:
    assert REFERENCE_EXCERPT_MAX == 300 and REFERENCE_EXCERPT_ELLIPSIS == "…"


# ---------- excerpt_of ----------


def test_short_text_unchanged() -> None:
    assert excerpt_of("Funnel accounts receive deposits.") == "Funnel accounts receive deposits."


def test_whitespace_collapsed_and_stripped() -> None:
    assert excerpt_of("  a \n\t b  c ") == "a b c"


def test_nfc_applied() -> None:
    decomposed = unicodedata.normalize("NFD", "한글 구절")
    assert excerpt_of(decomposed) == "한글 구절"


@pytest.mark.parametrize("value", [None, "", "   ", "\n\t"])
def test_empty_becomes_none(value: str | None) -> None:
    assert excerpt_of(value) is None


def test_exactly_300_units_kept() -> None:
    s = "a" * REFERENCE_EXCERPT_MAX
    assert excerpt_of(s) == s


def test_301_units_cut_to_299_plus_ellipsis() -> None:
    out = excerpt_of("a" * (REFERENCE_EXCERPT_MAX + 1))
    assert out == "a" * (REFERENCE_EXCERPT_MAX - 1) + REFERENCE_EXCERPT_ELLIPSIS
    assert utf16_len_nfc(out) == REFERENCE_EXCERPT_MAX


def test_surrogate_pair_on_cut_boundary_not_split() -> None:
    """298 유닛 + 😀(299·300번째 유닛) + 더 — 299 에서 자르면 대리쌍이 갈림 → 298 + `…`."""
    out = excerpt_of("a" * 298 + EMOJI + "bbbb")
    assert out is not None and out.endswith(REFERENCE_EXCERPT_ELLIPSIS)
    assert utf16_len_nfc(out) <= REFERENCE_EXCERPT_MAX
    assert out == "a" * 298 + REFERENCE_EXCERPT_ELLIPSIS
    out.encode("utf-16-le").decode("utf-16-le")  # 홀로 남은 대리 코드 없음


def test_emoji_fits_when_whole() -> None:
    """297 유닛 + 😀(298·299) + 긴 꼬리 → 😀 를 통째로 남기고 299 + `…` = 300."""
    out = excerpt_of("a" * 297 + EMOJI + "b" * 10)
    assert out == "a" * 297 + EMOJI + REFERENCE_EXCERPT_ELLIPSIS
    assert utf16_len_nfc(out) == REFERENCE_EXCERPT_MAX


def test_emoji_counts_two_units_under_limit() -> None:
    """파이썬 문자 수 300 이하라도 UTF-16 으로 300 넘으면 자름(백엔드 단위)."""
    s = EMOJI * 151  # 문자 151 · 유닛 302
    out = excerpt_of(s)
    assert out is not None and utf16_len_nfc(out) <= REFERENCE_EXCERPT_MAX and out.endswith("…")


# ---------- reference_excerpt (snippet → excerpt) ----------


def test_typology_pattern_sentence_preferred_over_head() -> None:
    text = (
        "This report covers general banking supervision topics. "
        "Funnel accounts receive many cash deposits from multiple individuals in different locations. "
        "Other content follows."
    )
    out = reference_excerpt(text, "FAN_IN")
    assert out is not None and out.startswith("Funnel accounts")


def test_no_pattern_falls_back_to_head() -> None:
    text = "Alpha beta. Gamma delta."
    assert reference_excerpt(text, None) == "Alpha beta. Gamma delta."


@pytest.mark.parametrize("text", [None, ""])
def test_no_body_is_none(text: str | None) -> None:
    assert reference_excerpt(text, "FAN_IN") is None


def test_long_pattern_sentences_end_with_ellipsis_at_300() -> None:
    """유형 패턴 문장 2개가 합쳐 300 을 넘으면 299 + `…`."""
    sentence = "Many senders deposit into one account " + "x" * 180 + "."
    out = reference_excerpt(f"{sentence} {sentence}", "FAN_IN")
    assert out is not None and out.endswith("…") and utf16_len_nfc(out) == REFERENCE_EXCERPT_MAX


def test_head_fallback_is_within_limit() -> None:
    """패턴 없음 → 앞 300자(snippet) — 공백 정리 뒤 300 안이면 `…` 없음."""
    out = reference_excerpt("word " * 200, None)
    assert out is not None and not out.endswith("…") and utf16_len_nfc(out) <= REFERENCE_EXCERPT_MAX


# ---------- excerpt_typology ----------


def test_excerpt_typology_follows_request_order() -> None:
    assert excerpt_typology(["FAN_OUT", "FAN_IN"], ("FAN_IN", "FAN_OUT")) == "FAN_OUT"
    assert excerpt_typology(["CYCLE", "FAN_IN"], ("FAN_IN",)) == "FAN_IN"


def test_excerpt_typology_none_without_overlap() -> None:
    assert excerpt_typology(["CYCLE"], ("FAN_IN",)) is None
    assert excerpt_typology([], ("FAN_IN",)) is None


# ---------- 스키마 ----------

_REF = {"chunk_id": "c", "doc_id": "d", "doc_title": "t", "page": 1, "score": 0.5}
_RES = {
    "doc_id": "d", "doc_title": "t", "publisher": None, "year": None, "page": 1, "score": 0.5,
    "chunk_id": "c", "typologies": ["FAN_IN"], "source_type": "PUBLIC",
}  # fmt: skip


def test_reference_field_order_excerpt_last() -> None:
    assert list(Reference.model_fields) == [
        "chunk_id",
        "doc_id",
        "doc_title",
        "page",
        "score",
        "text",
        "excerpt",
    ]
    dumped = Reference.model_validate({**_REF, "text": "x", "excerpt": "e"}).model_dump(exclude={"text"})
    assert list(dumped) == ["chunk_id", "doc_id", "doc_title", "page", "score", "excerpt"]


def test_reference_result_field_order_excerpt_last() -> None:
    assert list(ReferenceResult.model_fields) == [
        "doc_id", "doc_title", "publisher", "year", "page", "score", "chunk_id", "typologies", "source_type",
        "excerpt",
    ]  # fmt: skip


@pytest.mark.parametrize("model,base", [(Reference, _REF), (ReferenceResult, _RES)])
def test_excerpt_optional_and_old_json_passes(model, base) -> None:  # type: ignore[no-untyped-def]
    assert model.model_validate(base).excerpt is None
    assert model.model_validate({**base, "excerpt": None}).excerpt is None


@pytest.mark.parametrize("model,base", [(Reference, _REF), (ReferenceResult, _RES)])
def test_excerpt_over_300_units_rejected(model, base) -> None:  # type: ignore[no-untyped-def]
    model.model_validate({**base, "excerpt": "a" * 300})
    model.model_validate({**base, "excerpt": EMOJI * 150})  # 300 유닛
    with pytest.raises(ValidationError):
        model.model_validate({**base, "excerpt": "a" * 301})
    with pytest.raises(ValidationError):
        model.model_validate({**base, "excerpt": "a" * 299 + EMOJI})  # 문자 300 · 유닛 301
