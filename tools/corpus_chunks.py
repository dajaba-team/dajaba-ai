"""코퍼스의 쪽별 청크 분할·토큰 근사·유형 태그."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from hashlib import sha256
from math import ceil

from aml_ai.str.domain.constants import CJK_PATTERN, TOKEN_CHARS

_CJK = re.compile(CJK_PATTERN)


@dataclass(frozen=True)
class Chunk:
    page: int
    text: str
    tokens: int


def estimate_tokens(text: str) -> int:
    return max(ceil(len(text) / TOKEN_CHARS), len(_CJK.findall(text)))


def compute_content_hash(doc_id: str, page: int, text: str) -> str:
    text_norm = unicodedata.normalize("NFKC", text).strip()
    return sha256(f"{doc_id}\n{page}\n{text_norm}".encode()).hexdigest()


def resolve_typologies(doc_meta: dict, page: int) -> list[str]:
    page_map = doc_meta.get("typology_pages")
    if page_map:
        return [typology for typology, pages in page_map.items() if typology and page in (pages or [])]
    return [typology for typology in doc_meta.get("typologies", []) or [] if typology]


def _prefix_end(text: str, start: int, budget: int) -> int:
    end = min(len(text), start + budget * TOKEN_CHARS)
    cjk = 0
    for pos in range(start, end):
        cjk += bool(_CJK.fullmatch(text[pos]))
        if cjk > budget:
            return pos
    return end


def _page_chunks(text: str, page: int, tokens: int, overlap: int) -> list[Chunk]:
    chunks = []
    start = 0
    while start < len(text):
        end = _prefix_end(text, start, tokens)
        if end < len(text):
            for delimiter in ("\n\n", "\n", " "):
                boundary = text.rfind(delimiter, start, end)
                if boundary > start and estimate_tokens(text[start:boundary]) > overlap:
                    end = boundary + len(delimiter)
                    break
        body = text[start:end].strip()
        if body:
            chunks.append(Chunk(page=page, text=body, tokens=estimate_tokens(body)))
        if end == len(text):
            break
        overlap_chars = _prefix_end(text[start:end][::-1], 0, overlap)
        next_start = end - overlap_chars
        start = next_start if next_start > start else end
    return chunks


def chunk_pdf_pages(pages: list[str], tokens: int, overlap: int) -> list[Chunk]:
    if tokens <= 0 or not 0 <= overlap < tokens:
        raise ValueError("chunk tokens must be positive and 0 <= overlap < tokens")
    return [
        chunk
        for page, text in enumerate(pages, start=1)
        for chunk in _page_chunks(text, page, tokens, overlap)
    ]
