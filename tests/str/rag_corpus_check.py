"""SCRUM-305 태그 일관성 — 등급 → manifest 쪽 → DB 태그 청크 (docs/str/10 "305 실행 기록" 태그 도구 ⑧·⑬·⑭·⑱). 순수 함수.
기대 코퍼스 전체(기존 425 + 새 297, 위치·태그)를 DB 스냅샷 전체와 대조한다.

`run`·`preflight` 가 PreRun 을 만들기 전에 같은 DB 스냅샷으로 부른다. 등급 파일로 계산한 새 3문서 쪽이 manifest 와 다르거나
(등급 게시 뒤 manifest 교체 실패), 그 쪽의 새 청크 + 기존 CYCLE 2 가 DB 유형별 태그 청크와 다르면(다시 적재 안 함) 문제.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from tools.corpus_chunks import resolve_typologies

from tests.str.rag_corpus_tags import BASELINE_OLD_TAGGED, CORPUS_TYPOLOGIES, scope_problems, typology_pages
from tests.str.rag_eval_corpus_guard import normalized_sha256
from tests.str.rag_eval_corpus_preflight import NEW_DOC_IDS

SAME_KEYS = ("checked_by", "draft_sha256", "grades")  # 같은 입력인지 — 확인일은 빼고 봄
DRAFT_NAME = "answer_draft_corpus.json"  # 초벌 결과(CORPUS_EVAL_DIR)
LOCK_NAME = ".apply_corpus.lock"  # CORPUS_DIR/pdf(git 무시) — 교체하지 않는 공용 잠금
APPLIED_NAME = ".applied_corpus_grades.json"  # 이 코퍼스에 반영한 등급 해시 — 작업 트리가 달라도 같은 값만
OLD_DRAFT = "tests/str/rag_eval_v2/answer_draft.json"  # 275 초벌 — 기존 425 의 (chunk_id, 문서, 쪽)
# 기존 425 기대값(275 위치 + manifest 기존 줄 태그 — FAN_IN 19·FAN_OUT 6·CYCLE 2)의 정규화 sha256 고정값(⑱)
OLD_CORPUS_SHA256 = "07eae6fe21550add91a6713cd0a3b7e8e724e5f86d98b767056e9ccaacb87df6"
Rows = Mapping[str, tuple[str, int, tuple[str, ...]]]  # {chunk_id: (문서, 쪽, 태그 정렬 튜플)}


def grades_digest(grades_doc: Mapping[str, Any]) -> str:
    return normalized_sha256({k: grades_doc.get(k) for k in SAME_KEYS})


def old_rows_of(draft_275: Mapping[str, Any]) -> list[tuple[str, str, int]]:
    rows = {
        (r["chunk_id"], r["doc_id"], r["page"]) for v in draft_275["graded_by_typology"].values() for r in v
    }
    return sorted(rows)


def load_old_rows() -> list[tuple[str, str, int]]:
    """리포의 275 초벌 파일에서 기존 425 위치."""
    path = Path(__file__).parents[2] / OLD_DRAFT
    return old_rows_of(json.loads(path.read_text(encoding="utf-8")))


def corpus_sha256(rows: Rows) -> str:
    return normalized_sha256(sorted([c, d, p, sorted(ts)] for c, (d, p, ts) in rows.items()))


def corpus_ready_problems(
    *,
    grades_doc: Mapping[str, Any],
    applied_doc: Mapping[str, Any],
    draft_raw: bytes | None,
    manifest_documents: list[Mapping[str, Any]],
    old_rows: Iterable[tuple[str, str, int]],
    rows: Rows,
) -> list[str]:
    """예약·실행 전 — 등급 파일·공용 표식·초벌·manifest·DB 전체(같은 스냅샷 rows)가 서로 맞는지."""
    if not grades_doc:
        return ["등급 파일 없음 — apply-corpus 먼저"]
    if applied_doc.get("grades_sha256") != grades_digest(grades_doc):
        return ["공용 반영 표식이 없거나 등급 파일과 다름 — 같은 입력으로 apply-corpus 다시"]
    if draft_raw is None or sha256(draft_raw).hexdigest() != grades_doc.get("draft_sha256"):
        return ["초벌 파일이 없거나 등급 파일의 초벌과 다름"]
    old_rows = list(old_rows)
    bad = manifest_problems(manifest_documents, {d for _, d, _ in old_rows} | set(NEW_DOC_IDS))
    if bad:
        return bad
    docs, draft = {d["id"]: d for d in manifest_documents}, json.loads(draft_raw)
    loc = {c: (d, p) for c, (d, p, _) in rows.items()}
    ids = {t: [c for c, (_, _, ts) in rows.items() if t in ts] for t in CORPUS_TYPOLOGIES}
    old = {t: [c for c in v if loc[c][0] not in NEW_DOC_IDS] for t, v in ids.items()}
    out = scope_problems(draft, [(c, d, p) for c, (d, p) in loc.items() if d in NEW_DOC_IDS], old)
    out += tag_consistency_problems(grades_doc, docs, loc, ids)
    return out + corpus_problems(expected_corpus(old_rows, draft, docs), rows)


def manifest_problems(documents: list[Mapping[str, Any]], want_ids: set[str]) -> list[str]:
    """문서 표로 바꾸기 전 — id 집합 = want_ids(기존 425 문서 ∪ 새 3, 추가 검토 5) · 한 번씩 · 새 3문서 문서 단위 태그 빔."""
    counts = Counter(d.get("id") for d in documents)
    out = [f"manifest 에 {i} 가 {n}번" for i, n in counts.items() if n != 1]
    out += [f"manifest 에 {i} 줄이 없음" for i in sorted(want_ids - set(counts))]
    out += [f"manifest 에 모르는 id {i}" for i in sorted(set(counts) - want_ids, key=str)]
    doc_level = [d["id"] for d in documents if d.get("id") in NEW_DOC_IDS and d.get("typologies")]
    return out + [f"{i}: 문서 단위 typologies 가 있음" for i in doc_level]


def expected_corpus(
    old_rows: Iterable[tuple[str, str, int]], draft: Mapping[str, Any], docs: Mapping[str, Any]
) -> dict:
    """기존 425(275 위치) + 새 297(초벌 위치) — 태그는 manifest 로 `resolve_typologies`(적재와 같은 규칙)."""
    graded = draft.get("graded", {}).get(CORPUS_TYPOLOGIES[0], [])
    new = {(r["chunk_id"], r["doc_id"], r["page"]) for r in graded}
    return {c: (d, p, tuple(sorted(resolve_typologies(docs[d], p)))) for c, d, p in [*old_rows, *new]}


def corpus_problems(expected: Rows, rows: Rows) -> list[str]:
    """기대 = DB 전체가 아니면 문서별 개수(빠짐·더 있음·태그 다름). 기존 425 는 고정 해시와도 대조."""
    old = {c: v for c, v in expected.items() if v[0] not in NEW_DOC_IDS}
    out = (
        []
        if corpus_sha256(old) == OLD_CORPUS_SHA256
        else ["기존 425 기대값이 기준선과 다름(275 초벌·manifest)"]
    )
    by: dict[str, Counter] = {}
    for c in expected.keys() | rows.keys():
        a, b = expected.get(c), rows.get(c)
        kind = "빠짐" if b is None else "더 있음" if a is None else "태그 다름" if a != b else None
        if kind:
            by.setdefault((a or b)[0], Counter())[kind] += 1
    for d, n in sorted(by.items()):
        out.append(f"{d}: DB 가 기대 코퍼스와 다름 — " + " · ".join(f"{k} {v}" for k, v in sorted(n.items())))
    return out


def tag_consistency_problems(
    grades_doc: Mapping[str, Any],
    manifest_docs: Mapping[str, Mapping[str, Any]],
    loc: Mapping[str, tuple[str, int]],
    tagged_ids: Mapping[str, Iterable[str]],
) -> list[str]:
    """grades_doc = answers_corpus.json · manifest_docs = {id: 문서 줄} · loc = {chunk_id: (문서, 쪽)}(DB) · tagged_ids = DB 태그."""
    graded = {
        (t, g["chunk_id"]): int(g["grade"]) for t, rows in grades_doc.get("grades", {}).items() for g in rows
    }
    missing = sorted({c for _, c in graded if c not in loc})
    if missing:
        return [f"등급 파일의 청크가 DB 에 없음: {len(missing)}개"]
    pages = typology_pages(graded, loc)
    out = []
    for d in NEW_DOC_IDS:
        if (manifest_docs.get(d, {}).get("typology_pages") or {}) != {
            t: ps for t, ps in pages[d].items() if ps
        }:
            out.append(f"{d}: manifest 쪽이 확인 등급과 다름(반영 안 됨·실패)")
    for t in CORPUS_TYPOLOGIES:
        want = {c for c, (d, p) in loc.items() if d in NEW_DOC_IDS and p in pages[d].get(t, [])}
        want |= set(BASELINE_OLD_TAGGED[t])
        if set(tagged_ids.get(t, ())) != want:
            out.append(f"{t}: DB 태그 청크가 확인 등급·manifest 와 다름(다시 적재 안 함)")
    return out
