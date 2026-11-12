"""narrative_v3 REFERENCES 렌더링 — 최대 2건 · 유형 패턴 문장 1~2개 (docs/str/05 narrative_v3, SCRUM-225).

문장 고르기: 청크를 문장으로 나눠 `TYPOLOGY_PATTERN_EN[유형]` 과 영단어(앞 5자) 겹침이 큰 순으로 고르고
원문 순서로 붙인다. 겹침 0·패턴 없음 → 앞 300자. 추가 임베딩 호출 없음. v1·v2·rewrite_v1 은 안 씀.
"""

from __future__ import annotations

import re

from aml_ai.shared.schemas.str import Reference
from aml_ai.str.domain.constants_references import (
    REFERENCE_SNIPPET_FALLBACK_CHARS,
    REFERENCE_SNIPPET_MIN_WORD,
    REFERENCE_SNIPPET_PROMPTS,
    REFERENCE_SNIPPET_SENTENCES,
    REFERENCE_SNIPPET_STEM_CHARS,
    REFERENCES_PROMPT_MAX,
)
from aml_ai.str.infrastructure.retriever import TYPOLOGY_PATTERN_EN

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z]+")


def uses_snippet(prompt_name: str) -> bool:
    return prompt_name in REFERENCE_SNIPPET_PROMPTS


def prompt_references(prompt_name: str, references: list[Reference]) -> list[Reference]:
    """프롬프트와 generation_meta 가 같이 쓰는 참고 사례 — v3 는 검색 순위 앞 2건, 그 밖은 그대로."""
    return references[:REFERENCES_PROMPT_MAX] if uses_snippet(prompt_name) else references


def _stems(text: str) -> set[str]:
    words = _WORD.findall(text.lower())
    return {w[:REFERENCE_SNIPPET_STEM_CHARS] for w in words if len(w) >= REFERENCE_SNIPPET_MIN_WORD}


def snippet(text: str | None, typology: str | None) -> str:
    if not text:
        return ""
    fallback = text[:REFERENCE_SNIPPET_FALLBACK_CHARS].strip()
    pattern = _stems(TYPOLOGY_PATTERN_EN.get(typology or "", ""))
    if not pattern:
        return fallback
    sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
    scored = [(len(_stems(s) & pattern), i) for i, s in enumerate(sentences)]
    top = sorted((x for x in scored if x[0] > 0), key=lambda x: (-x[0], x[1]))[:REFERENCE_SNIPPET_SENTENCES]
    if not top:
        return fallback
    return " ".join(sentences[i] for _, i in sorted(top, key=lambda x: x[1]))


def render_references(references: list[Reference], typology: str | None, *, snippet_mode: bool) -> str:
    """`[n] {doc_title} p.{page}: {본문}` 줄들 또는 `(없음)`. snippet_mode=False 면 v1·v2 그대로(청크 전체)."""
    lines = [
        f"[{i + 1}] {r.doc_title} p.{r.page}: {snippet(r.text, typology) if snippet_mode else (r.text or '')}"
        for i, r in enumerate(references)
    ]
    return "\n".join(lines) or "(없음)"
