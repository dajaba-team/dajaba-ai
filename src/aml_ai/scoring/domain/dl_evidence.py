"""DL 순위 응답의 근거 신원 칸을 계산한다 (scoring/01 "근거 신원 칸")."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime


def evidence_digest(sources: Iterable[tuple[str, int]]) -> str:
    """근거 거래의 (원본파일명, 원본행번호)로 경보 근거 집합의 SHA-256을 만든다."""
    text = "\n".join(f"{source_file}:{row_number}" for source_file, row_number in sorted(sources))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reference_text(reference: datetime) -> str:
    """경보 기준 시각을 `YYYY-MM-DDTHH:MM:SS` 문자열로 만든다."""
    return reference.isoformat(timespec="seconds")
