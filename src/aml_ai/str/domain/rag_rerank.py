"""SCRUM-308-2 리랭커 — 표지·순서 검사·적용·user 문장 만들기 (docs/str/10 "리랭커", 05 "rerank_v1"). 순수.

후보는 표지 `C1`~`Cn`(지금 순서)로만 LLM 에 보이고, 응답은 표지 순서. 응답이 후보 표지의 **순열**이 아니면
(빠짐·중복·없는 표지) None — 호출 측이 원래 순서로(fail-open). `Reference.score` 는 손대지 않음(순서만).
"""

from __future__ import annotations

import unicodedata

from aml_ai.shared.schemas.str import Facts, Reference
from aml_ai.str.domain.constants_rag_query import RERANK_LABEL_PREFIX
from aml_ai.str.domain.constants_rerank_registry import RAG_RERANK_REGISTRY_V1
from aml_ai.str.domain.rag_queries import build_query


def labels(count: int) -> list[str]:
    return [f"{RERANK_LABEL_PREFIX}{i}" for i in range(1, count + 1)]


def reorder(refs: list[Reference], order: list[str]) -> list[Reference] | None:
    """응답 표지 순서로 다시 줄 세움. 순열이 아니면 None."""
    names = labels(len(refs))
    if len(order) != len(names) or set(order) != set(names):
        return None
    by_label = dict(zip(names, refs, strict=True))
    return [by_label[label] for label in order]


def isolate(text: str) -> str:
    """격리 블록을 본문이 닫지 못하게 — NFKC(전각 `＜` → `<`) 뒤 `<`·`>` 를 바꿈(05 rerank_v1 규칙 3, ask 와 같음)."""
    return unicodedata.normalize("NFKC", text).replace("<", "&lt;").replace(">", "&gt;")


def render_user(template: str, query: str, texts: list[str]) -> str:
    """user 문장 — `{{query}}`·`{{candidates}}` 를 한 번에 바꿈(본문 속 자리표시를 다시 바꾸지 않게)."""
    blocks = "\n\n".join(
        f'<candidate id="{label}">\n{isolate(body)}\n</candidate>'
        for label, body in zip(labels(len(texts)), texts, strict=True)
    )
    values = {"{{query}}": f"<query>{isolate(query)}</query>", "{{candidates}}": blocks}
    head, sep, tail = template.partition("{{query}}")
    if not sep:
        raise ValueError("rerank template needs {{query}}")
    before, sep2, after = tail.partition("{{candidates}}")
    if not sep2:
        raise ValueError("rerank template needs {{candidates}}")
    return head + values["{{query}}"] + before + values["{{candidates}}"] + after


def rerank_query(facts: Facts) -> str | None:
    """리랭커에 보낼 질의 = (a) `build_query`. 신호·업종 중 하나라도 등록 목록 V1 밖이면 None — 원래 순서(추가 검토 2)."""
    industry = facts.customer.industry if facts.customer else None
    if any(s not in RAG_RERANK_REGISTRY_V1["signals"] for s in facts.model_signals):
        return None
    if industry is not None and industry not in RAG_RERANK_REGISTRY_V1["industries"]:
        return None
    return build_query(facts)
