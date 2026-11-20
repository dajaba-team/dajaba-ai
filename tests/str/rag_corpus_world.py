"""SCRUM-305 태그 도구 테스트용 합성 코퍼스 — 기존 425(실제 275 초벌 위치 + manifest 기존 줄 태그) + 새 3문서 34·17·246(합성 id).

DB 는 `rows` = {chunk_id: (문서, 쪽, 태그 튜플)} 하나. 예약 회귀(추가 검토 3·4)가 실제 `corpus_ready_problems` 로 쓴다.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from tools.corpus_chunks import resolve_typologies

from tests.str import rag_corpus_check as ck
from tests.str import rag_corpus_tags as tags
from tests.str.rag_eval_corpus_preflight import NEW_DOC_IDS

REPO = Path(__file__).parents[2]
APG, FIN, FTR = "apg-typologies-2025", "fincen-cmln-2025", "fintrac-underground-banking-2023"
OLD = list(tags.BASELINE_OLD_TAGGED["CYCLE"])
NEW = [
    (f"{n:02x}{i:062x}", d, i % 8 + 1)
    for n, (d, k) in enumerate(tags.NEW_DOC_CHUNKS.items())
    for i in range(k)
]
HIT = next(c for c, d, p in NEW if d == APG and p == 3)  # 확인자가 CYCLE 2 를 준 청크


def old_rows() -> list[tuple[str, str, int]]:
    return ck.load_old_rows()


def world() -> dict:
    old = old_rows()
    loc = {c: (d, p) for c, d, p in [*NEW, *old]}
    draft = tags.draft_doc([(c, d, p, c) for c, d, p in NEW], lambda t, ty: int(t == HIT and ty == "CYCLE"),
                           prompt_sha256="ab" * 32, model="m")  # fmt: skip
    raw = json.dumps(draft).encode()
    scope = tags.sheet_scope(draft, NEW, {"CYCLE": OLD}, {c: loc[c] for c in OLD})
    graded = {(t, c): 2 if c == HIT else (1 if c in OLD else 0) for t, c, _, _ in scope}
    grades = tags.answers_doc(graded, scope, checker="김종민", checked_at="2026-11-21",
                              draft_sha256=sha256(raw).hexdigest())  # fmt: skip
    text = (REPO / "corpus/manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(tags.manifest_with_pages(text, tags.typology_pages(graded, loc)))
    docs = {d["id"]: d for d in manifest["documents"]}
    rows = {c: (d, p, tuple(resolve_typologies(docs[d], p))) for c, (d, p) in loc.items()}
    return {"rows": rows, "raw": raw, "grades": grades, "manifest": manifest,
            "applied": {"grades_sha256": ck.grades_digest(grades)}}  # fmt: skip


def ids_of(rows: dict) -> dict[str, list[str]]:
    keys = ("CYCLE", "SCATTER_GATHER", "GATHER_SCATTER", "FX_RELAY")
    return {t: sorted(c for c, (_, _, ts) in rows.items() if t in ts) for t in keys}


def problems(w: dict) -> list[str]:
    return ck.corpus_ready_problems(grades_doc=w["grades"], applied_doc=w["applied"], draft_raw=w["raw"],
                                    manifest_documents=w["manifest"]["documents"], old_rows=old_rows(),
                                    rows=w["rows"])  # fmt: skip


def without_doc(rows: dict, doc_id: str) -> dict:
    return {c: v for c, v in rows.items() if v[0] != doc_id}


def with_tags(rows: dict, chunk_id: str, *extra: str) -> dict:
    d, p, ts = rows[chunk_id]
    return rows | {chunk_id: (d, p, tuple(sorted({*ts, *extra})))}


def untagged_manifest() -> str:
    """리포 manifest 에서 새 3줄의 `typology_pages` 만 뺀 것 — 태그 반영 전 모양(반영 뒤에도 같은 입력)."""
    text = (REPO / "corpus/manifest.json").read_text(encoding="utf-8")
    for doc_id in NEW_DOC_IDS:
        text = _edit_line(text, doc_id, lambda doc: doc.pop("typology_pages", None))
    return text


def _with_line(text: str, doc_id: str, **extra) -> str:
    return _edit_line(text, doc_id, lambda doc: doc.update(extra))


def _edit_line(text: str, doc_id: str, edit) -> str:  # noqa: ANN001
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if f'"id": "{doc_id}"' in line:
            comma = "," if line.rstrip().endswith(",") else ""
            doc = json.loads(line.strip().rstrip(","))
            edit(doc)
            lines[i] = "    " + json.dumps(doc, ensure_ascii=False) + comma
    return "\n".join(lines) + "\n"
