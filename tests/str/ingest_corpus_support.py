"""SCRUM-125 — ingest_corpus 테스트 공용 헬퍼 (PDF·manifest 조립, 가짜 embedder)."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pymupdf  # type: ignore[import-untyped]

_DIM = 1536


def make_pdf(path: Path, pages: list[str]) -> tuple[str, int]:
    """쪽별 텍스트로 작은 PDF 생성. (sha256, pages) 반환."""
    doc = pymupdf.open()
    for page_text in pages:
        p = doc.new_page()  # type: ignore[attr-defined]
        p.insert_text((50, 100), page_text, fontsize=11)
    doc.save(str(path))
    doc.close()
    data = path.read_bytes()
    return sha256(data).hexdigest(), len(pages)


class FakeEmbedder:
    """고정 벡터 1536차원. 입력 수만큼 반환."""

    def __init__(self, dim: int = _DIM) -> None:
        self._vec = [0.1] + [0.0] * (dim - 1)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec for _ in texts]


def write_manifest(tmp_path: Path, documents: list[dict[str, Any]]) -> dict[str, Any]:
    """documents 리스트를 받아 manifest.json 쓰고 dict 그대로 돌려줌."""
    manifest = {"documents": documents}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def doc_meta(
    doc_id: str,
    sha: str,
    pages: int,
    *,
    typologies: list[str] | None = None,
    typology_pages: dict[str, list[int]] | None = None,
) -> dict[str, Any]:
    """manifest 문서 한 건의 공통 모양."""
    m: dict[str, Any] = {
        "id": doc_id,
        "title": doc_id,
        "publisher": "T",
        "year": 2026,
        "lang": "en",
        "url": "u",
        "sha256": sha,
        "pages": pages,
    }
    if typologies is not None:
        m["typologies"] = typologies
    if typology_pages is not None:
        m["typology_pages"] = typology_pages
    return m


def seed_pdf(corpus_dir: Path, doc_id: str, pages_text: list[str]) -> str:
    """corpus_dir/pdf/<doc_id>.pdf 로 PDF 두고 sha256 반환."""
    pdf_dir = corpus_dir / "pdf"
    pdf_dir.mkdir(exist_ok=True)
    pdf_path = pdf_dir / f"{doc_id}.pdf"
    sha, _ = make_pdf(pdf_path, pages_text)
    return sha
