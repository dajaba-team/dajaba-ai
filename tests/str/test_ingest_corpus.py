"""SCRUM-125 — tools/ingest_corpus.py 단위 테스트 (docs/str/10, INTENT 새 파일).

- 청크 토큰 근사식: `tokens ≈ max(ceil(chars_total/4), chars_korean)` — 09 2026-11-11
- `content_hash = sha256(doc_id + "\\n" + page + "\\n" + text_norm)`, text_norm = NFKC + 좌우 공백 정돈
- 태그 분기 3개: `typology_pages` (쪽 단위) / `typologies` (문서 단위) / 둘 다 없음 (빈 태그)
- 청크 쪽 경계 유지

DB 결정적 판(멱등·--truncate·sha256 skip)은 `test_ingest_corpus_db.py (-m db)`.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any

# ── 단위: 토큰 근사식 ──────────────────────────────────────────────────────


def test_chunk_size_estimate_english() -> None:
    """영문: chars_total/4 가 tokens."""
    from tools.ingest_corpus import estimate_tokens

    text_en = "a" * 400  # 400자 → 약 100 토큰
    tokens = estimate_tokens(text_en)
    assert tokens == 100


def test_chunk_size_estimate_korean_dominates() -> None:
    """한글 다수: chars_korean 이 chars/4 보다 크면 그 값을 토큰으로 (안전측)."""
    from tools.ingest_corpus import estimate_tokens

    text_ko = "가" * 100  # 한글 100자 → 100 토큰 (chars/4=25 보다 큼)
    tokens = estimate_tokens(text_ko)
    assert tokens == 100


def test_chunk_size_estimate_mixed() -> None:
    """혼합: max(ceil(chars/4), chars_korean)."""
    from tools.ingest_corpus import estimate_tokens

    text = "abcd" * 100 + "가" * 50  # chars=450, korean=50, chars/4≈113
    tokens = estimate_tokens(text)
    assert tokens == 113  # ceil(450/4)=113


# ── 단위: content_hash ─────────────────────────────────────────────────────


def _expected_hash(doc_id: str, page: int, text_norm: str) -> str:
    return sha256(f"{doc_id}\n{page}\n{text_norm}".encode()).hexdigest()


def test_content_hash_is_sha256_doc_page_text() -> None:
    """공식 그대로 — 재적재해도 같은 id (chunk_id = content_hash, 126 평가 단위)."""
    from tools.ingest_corpus import compute_content_hash

    h = compute_content_hash("fincen-funnel-2014", 1, "Funnel Account definition.")
    assert h == _expected_hash("fincen-funnel-2014", 1, "Funnel Account definition.")
    assert len(h) == 64


def test_content_hash_text_norm_strips_whitespace_and_nfkc() -> None:
    """text_norm = NFKC + 좌우 공백 정돈. 같은 뜻 문자열이면 같은 hash."""
    from tools.ingest_corpus import compute_content_hash

    # NFKC: ｶ (U+FF76) → カ (U+30AB)
    h_nfkc = compute_content_hash("docA", 1, "ｶﾌｪ")  # 반각 가타카나
    h_plain = compute_content_hash("docA", 1, "カフェ")  # 전각 가타카나
    assert h_nfkc == h_plain

    # 좌우 공백 정돈
    h_spaced = compute_content_hash("docA", 1, "  Funnel Account.  ")
    h_trimmed = compute_content_hash("docA", 1, "Funnel Account.")
    assert h_spaced == h_trimmed


def test_same_paragraph_two_docs_both_kept() -> None:
    """같은 문단이 두 문서에 있으면 doc_id 가 다르므로 content_hash 가 다름 → 두 청크 다 남음."""
    from tools.ingest_corpus import compute_content_hash

    paragraph = "Multiple accounts receive cash deposits."
    h_a = compute_content_hash("doc-a", 1, paragraph)
    h_b = compute_content_hash("doc-b", 1, paragraph)
    assert h_a != h_b


# ── 단위: 태그 분기 ────────────────────────────────────────────────────────


def test_typology_pages_in_pages_tagged() -> None:
    """typology_pages 가 있으면 목록 안 쪽만 그 태그."""
    from tools.ingest_corpus import resolve_typologies

    doc_meta: dict[str, Any] = {
        "id": "fatf-pml-2018",
        "typologies": [],
        "typology_pages": {"FAN_IN": [43, 44]},
    }
    assert resolve_typologies(doc_meta, page=43) == ["FAN_IN"]
    assert resolve_typologies(doc_meta, page=44) == ["FAN_IN"]


def test_typology_pages_out_of_pages_empty() -> None:
    """typology_pages 가 있어도 목록 밖 쪽은 빈 태그 (문서 단위 fallback 없음)."""
    from tools.ingest_corpus import resolve_typologies

    doc_meta: dict[str, Any] = {
        "id": "fatf-pml-2018",
        "typologies": [],
        "typology_pages": {"FAN_IN": [43, 44]},
    }
    assert resolve_typologies(doc_meta, page=1) == []
    assert resolve_typologies(doc_meta, page=42) == []
    assert resolve_typologies(doc_meta, page=45) == []


def test_typologies_document_level_applies_to_all_pages() -> None:
    """typologies 만 있으면 모든 쪽 청크가 같은 태그."""
    from tools.ingest_corpus import resolve_typologies

    doc_meta: dict[str, Any] = {
        "id": "ffiec-redflags",
        "typologies": ["FAN_IN", "FAN_OUT", "CYCLE"],
    }
    assert resolve_typologies(doc_meta, page=1) == ["FAN_IN", "FAN_OUT", "CYCLE"]
    assert resolve_typologies(doc_meta, page=8) == ["FAN_IN", "FAN_OUT", "CYCLE"]


def test_no_typology_keys_means_empty_tag() -> None:
    """둘 다 없거나 둘 다 빈 값이면 빈 태그 (검색 결과에 안 나옴)."""
    from tools.ingest_corpus import resolve_typologies

    assert resolve_typologies({"id": "docA"}, page=1) == []
    assert resolve_typologies({"id": "docA", "typologies": []}, page=1) == []
    assert resolve_typologies({"id": "docA", "typologies": [], "typology_pages": {}}, page=1) == []


# ── 단위: 쪽 경계 유지 청크 분할 ──────────────────────────────────────────


def test_pdf_page_boundary_preserved() -> None:
    """청크가 쪽 경계를 넘지 않음 — 각 청크의 page 가 하나."""
    from tools.ingest_corpus import chunk_pdf_pages

    pages = [
        "Page 1 text about funnel accounts " * 20,
        "Page 2 text about different topic " * 20,
    ]
    chunks = chunk_pdf_pages(pages, tokens=500, overlap=50)
    assert chunks, "청크 없음"
    for c in chunks:
        assert c.page in (1, 2)
    # 1쪽 내용이 2쪽 청크에 섞이지 않음
    for c in chunks:
        if c.page == 1:
            assert "Page 2" not in c.text
        else:
            assert "Page 1" not in c.text
