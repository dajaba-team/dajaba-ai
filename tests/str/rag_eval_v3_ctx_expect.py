"""SCRUM-308 ③ 청크 맥락 — 기준 커밋으로 계산한 기대값 대조 (추가 검토 1, docs/str/10 "청크 맥락").

기대 태그·머리말 = 87aef09 의 manifest(바이트 대조, 위치표 `manifest_sha256` 과도 같아야) + 위치표(chunk_id → 문서·쪽).
같은 스냅샷에서 **두 표의 청크별 태그·문서·쪽·머리말 메타가 기대와 정확히 같을 때만** 진행(개수가 같아도 내용이 다르면 거절).
재검사 대상 = 기대 매핑 전체(722 — 검토 2, 순위·태그와 무관). 새 표 재검사 문장은 기대 머리말 + 본문.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session
from tools.corpus_chunks import compute_content_hash, resolve_typologies

from aml_ai.str.domain.chunk_context import context_header, context_text
from aml_ai.str.domain.constants_rag_query import REFERENCE_CTX_TABLE, REFERENCE_TABLES
from tests.str import rag_eval_v3_cutoff_guard as cg

MANIFEST = "corpus/manifest.json"


def read_manifest(repo: Path, positions: dict[str, Any]) -> tuple[dict | None, str | None, str | None]:
    """(문서 id → manifest 줄, sha256, 이유) — 기준 커밋 바이트와 같고 위치표가 만든 manifest 와 같아야."""
    loaded, digests, reason = cg.read_committed(repo, (MANIFEST,))
    if reason or loaded is None:
        return None, None, reason
    if digests[MANIFEST] != positions.get("manifest_sha256"):
        return None, None, "manifest 가 위치표의 manifest_sha256 과 다름"
    return {d["id"]: d for d in loaded[MANIFEST]["documents"]}, digests[MANIFEST], None


def expected(docs: dict[str, dict], positions: dict[str, dict]) -> dict[str, dict[str, Any]]:
    """chunk_id → {doc_id, page, tags(정렬), meta(제목·발행처·연도), header}. 적재 도구와 같은 태그 규칙·머리말 함수."""
    out = {}
    for cid, p in positions.items():
        d = docs[p["doc_id"]]
        out[cid] = {"doc_id": p["doc_id"], "page": p["page"], "tags": sorted(resolve_typologies(d, p["page"])),
                    "meta": (d["title"], d.get("publisher"), d.get("year")),
                    "header": context_header(d["title"], d.get("publisher"), d.get("year"), p["page"])}  # fmt: skip
    return out


def table_problem(session: Session, table: str, expect: dict[str, dict[str, Any]]) -> str | None:
    """표의 chunk_id 집합·청크별 태그·문서·쪽·머리말 메타가 기대와 정확히 같고, 행마다 본문 해시
    `compute_content_hash(doc_id, page, text)` = chunk_id = 저장 `content_hash`(검토 2 — 본문 교체도 거절). 이유는 개수만."""
    if table not in REFERENCE_TABLES:
        raise ValueError("unknown reference table")
    rows = session.execute(
        text(
            f"SELECT chunk_id, doc_id, page, typologies, doc_title, publisher, year, text, content_hash FROM {table}"
        )  # noqa: S608
    ).all()
    if {r.chunk_id for r in rows} != set(expect):
        return f"{table} chunk_id 집합이 기준 위치표와 다름"
    tags = sum(sorted(r.typologies) != expect[r.chunk_id]["tags"] for r in rows)
    place = sum(
        (r.doc_id, r.page) != (expect[r.chunk_id]["doc_id"], expect[r.chunk_id]["page"]) for r in rows
    )
    meta = sum((r.doc_title, r.publisher, r.year) != expect[r.chunk_id]["meta"] for r in rows)
    body = sum(
        not (compute_content_hash(r.doc_id, r.page, r.text) == r.chunk_id == r.content_hash) for r in rows
    )
    if tags or place or meta or body:
        return f"{table} 기대와 다른 청크 — 태그 {tags} · 문서·쪽 {place} · 머리말 메타 {meta} · 본문 해시 {body}"
    return None


def stored(
    session: Session, table: str, ids: list[str], model: str, expect: dict
) -> dict[str, tuple[str, list[float]]]:
    """재검사 행 — (임베딩에 넣었어야 할 문장, 저장 벡터). 새 표는 기대 머리말 + 본문, 지금 표는 본문. 빠진 id 는 대조에서 실패."""
    rows = session.execute(
        text(f"SELECT chunk_id, text, embedding::text AS vec FROM {table} "  # noqa: S608 — 허용 목록 표
             "WHERE chunk_id = ANY(:ids) AND embedding_model = :model"), {"ids": ids, "model": model},
    ).all() if table in REFERENCE_TABLES else []  # fmt: skip
    ctx = table == REFERENCE_CTX_TABLE
    got = {
        r.chunk_id: (context_text(expect[r.chunk_id]["header"], r.text) if ctx else r.text, json.loads(r.vec))
        for r in rows
    }
    if set(got) != set(ids):
        raise ValueError(f"{table} 재검사 대상 {len(ids)} 중 {len(ids) - len(got)} 없음")
    return got
