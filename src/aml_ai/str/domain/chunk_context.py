"""SCRUM-308-3 청크 맥락 머리말 — 순수 (docs/str/10 "청크 맥락", 기준 `87aef09` ③).

`{title} — {publisher}, {year}, p.{page}` 한 줄 + 줄바꿈 + 본문. 연도가 없으면 `, {year}` 칸만 생략(ffiec-redflags).
임베딩 입력에만 씀 — 저장 `text`·화면 `Reference.text` 는 머리말 없는 원래 본문.
"""

from __future__ import annotations


def context_header(title: str | None, publisher: str | None, year: int | None, page: int) -> str:
    if not (title or "").strip() or not (publisher or "").strip():
        raise ValueError("chunk context header needs title and publisher")
    where = publisher if year is None else f"{publisher}, {year}"
    return f"{title} — {where}, p.{page}"


def context_text(header: str, body: str) -> str:
    return f"{header}\n{body}"
