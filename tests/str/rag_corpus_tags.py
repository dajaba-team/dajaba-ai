"""SCRUM-305 태그 도구 순수 부분 (docs/str/10 "305 실행 기록" 태그 도구). DB·LLM 0.

초벌(새 3문서 청크 × CYCLE·SG·GS) → 확인 시트 범위(유형별 후보 쪽의 새 청크 전부 + 기존 태그 청크 전부) →
확인 등급 → 새 3문서 `typology_pages`(확인 ≥ 1 청크의 쪽) → manifest 의 새 3줄만 바꿈. FAN·FX_RELAY 는 다루지 않음.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from tests.str.rag_eval_corpus_preflight import NEW_DOC_IDS

CORPUS_TYPOLOGIES = ("CYCLE", "SCATTER_GATHER", "GATHER_SCATTER")
ROW_PREFIX = {"CYCLE": "CY", "SCATTER_GATHER": "SG", "GATHER_SCATTER": "GS"}
GRADE_MIN = 1
NEW_DOC_CHUNKS = {"fincen-cmln-2025": 34, "fintrac-underground-banking-2023": 17, "apg-typologies-2025": 246}
# 적재 전 코퍼스에서 이미 CYCLE 로 태그된 청크(ffiec-redflags p6 두 개, manifest CYCLE [6]) — SG·GS 는 0
BASELINE_OLD_TAGGED = {
    "CYCLE": ("9761a3b1efd701833f1e550e051b6727f70585a3eef3bd355a19b8e91ffa2a7f",
              "d994051861cbf0626d93ddce92d3af60ec5d69797774c1200b1df9a8adbd2234"),
    "SCATTER_GATHER": (),
    "GATHER_SCATTER": (),
}  # fmt: skip
Scope = list[tuple[str, str, str, int]]  # (유형, chunk_id, doc_id, page)


def draft_doc(
    rows: Iterable[tuple[str, str, int, str]],
    grade: Callable[[str, str], int],
    *,
    prompt_sha256: str,
    model: str,
) -> dict[str, Any]:
    """rows = (chunk_id, doc_id, page, 본문) — 새 3문서만. 결과에는 본문 없음."""
    rows = list(rows)
    if any(d not in NEW_DOC_IDS for _, d, _, _ in rows):
        raise ValueError("초벌은 새 3문서 청크만")
    graded = {t: [{"chunk_id": c, "doc_id": d, "page": p, "grade": int(grade(text, t))} for c, d, p, text in rows]
              for t in CORPUS_TYPOLOGIES}  # fmt: skip
    return {"prompt_version": "rag_answer_v2", "prompt_sha256": prompt_sha256, "model": model,
            "chunks": len(rows), "graded": graded}  # fmt: skip


def loaded_problems(rows: Iterable[tuple[str, str, int, str]]) -> list[str]:
    """초벌 전체 실행 전 — DB 의 새 3문서 청크 수가 34·17·246 인지."""
    counts = {d: 0 for d in NEW_DOC_CHUNKS}
    for _, d, _, _ in rows:
        counts[d] = counts.get(d, 0) + 1
    return [] if counts == NEW_DOC_CHUNKS else [f"새 3문서 청크 수 {counts} ≠ {NEW_DOC_CHUNKS}"]


def scope_problems(
    draft: Mapping[str, Any],
    db_new: Iterable[tuple[str, str, int]],
    old_tagged: Mapping[str, Iterable[str]],
    expect: Mapping[str, int] = NEW_DOC_CHUNKS,
) -> list[str]:
    """export·apply 전 — 유형별 초벌 (chunk_id, 문서, 쪽) 전체 = DB 새 3문서 청크 전체 · 기존 태그 청크 = 기준선."""
    db = {(c, d, p) for c, d, p in db_new}
    counts = {d: sum(1 for _, dd, _ in db if dd == d) for d in expect}
    out = [] if counts == dict(expect) else [f"DB 새 3문서 청크 수 {counts} ≠ {dict(expect)}"]
    for t in CORPUS_TYPOLOGIES:
        got = {(r["chunk_id"], r["doc_id"], r["page"]) for r in draft.get("graded", {}).get(t, [])}
        if got != db:
            out.append(f"{t}: 초벌 청크 집합이 DB 와 다름(초벌 {len(got)} · DB {len(db)})")
        if sorted(old_tagged.get(t, ())) != sorted(BASELINE_OLD_TAGGED[t]):
            out.append(f"{t}: 기존 태그 청크가 기준선과 다름")
    return out


def candidate_pages(draft: Mapping[str, Any]) -> dict[str, set[tuple[str, int]]]:
    """유형 → 초벌 ≥ 1 청크가 있는 (doc_id, page)."""
    return {
        t: {(r["doc_id"], r["page"]) for r in draft["graded"][t] if r["grade"] >= GRADE_MIN}
        for t in CORPUS_TYPOLOGIES
    }


def sheet_scope(
    draft: Mapping[str, Any],
    new_chunks: Iterable[tuple[str, str, int]],
    old_tagged: Mapping[str, Iterable[str]],
    old_loc: Mapping[str, tuple[str, int]],
) -> Scope:
    """유형별 ① 후보 쪽의 새 청크 전부(쪽 단위 태그 범위) ② 그 유형으로 이미 태그된 기존 청크 전부."""
    cand, new_chunks = candidate_pages(draft), list(new_chunks)
    scope = [(t, c, d, p) for t in CORPUS_TYPOLOGIES for c, d, p in new_chunks if (d, p) in cand[t]]
    scope += [(t, c, *old_loc[c]) for t in CORPUS_TYPOLOGIES for c in old_tagged.get(t, ())]
    return sorted(set(scope), key=_order)


def _order(row: tuple[str, str, str, int]) -> tuple:
    t, c, d, p = row
    return CORPUS_TYPOLOGIES.index(t), d, p, c


def numbered(scope: Scope) -> list[tuple[str, str, str, str, int]]:
    """(행 id, 유형, chunk_id, doc_id, page) — 범위 순서와 무관하게 같은 번호."""
    out, counts = [], dict.fromkeys(CORPUS_TYPOLOGIES, 0)
    for t, c, d, p in sorted(set(scope), key=_order):
        counts[t] += 1
        out.append((f"{ROW_PREFIX[t]}-{counts[t]:03d}", t, c, d, p))
    return out


def grade_key(typology: str, chunk_id: str) -> str:
    """등급 칸 앞 ID — (유형, chunk_id)로 계산(추가 검토 3). 순번 `CY-001` 은 표시용."""
    return f"{ROW_PREFIX[typology]}-{chunk_id[:8]}"


def answers_doc(
    graded: Mapping[tuple[str, str], int], scope: Scope, *, checker: str, checked_at: str, draft_sha256: str
) -> dict[str, Any]:
    if not checker.strip():
        raise ValueError("확인자 이름이 없음")
    want = {(t, c) for t, c, _, _ in scope}
    if set(graded) != want or any(g not in (0, 1, 2) for g in graded.values()):
        raise ValueError("확인 등급이 시트 범위와 다르거나 0·1·2 가 아님")
    grades = {t: [{"chunk_id": c, "grade": graded[(t, c)]} for tt, c, _, _ in sorted(scope, key=_order) if tt == t]
              for t in CORPUS_TYPOLOGIES}  # fmt: skip
    return {
        "checked_by": checker.strip(),
        "checked_at": checked_at,
        "draft_sha256": draft_sha256,
        "grades": grades,
    }


def typology_pages(
    grades: Mapping[tuple[str, str], int], loc: Mapping[str, tuple[str, int]]
) -> dict[str, dict[str, list[int]]]:
    """새 3문서만 — 유형별 확인 등급 ≥ 1 청크가 있는 쪽."""
    out: dict[str, dict[str, set[int]]] = {}
    for (t, c), g in grades.items():
        d, p = loc[c]
        if g >= GRADE_MIN and d in NEW_DOC_IDS:
            out.setdefault(d, {}).setdefault(t, set()).add(p)
    return {d: {t: sorted(ps) for t, ps in sorted(out.get(d, {}).items())} for d in sorted(NEW_DOC_IDS)}


def manifest_with_pages(text: str, pages: Mapping[str, Mapping[str, list[int]]]) -> str:
    """새 3줄의 `typology_pages` 를 최종 쪽 목록으로 통째로 바꿈(0 이 된 쪽은 지움). 기존 줄은 글자 그대로.

    거절: 새 3문서 전부가 아님·FAN·FX_RELAY·모르는 유형 · manifest 에 새 id 가 한 번씩이 아님 · 한 줄 한 문서 모양이 아님 ·
    원본 새 3줄에 이미 FAN·FX_RELAY. 쓴 결과를 다시 파싱해 요청과 같은지 확인.
    """
    if set(pages) != set(NEW_DOC_IDS) or any(not set(by) <= set(CORPUS_TYPOLOGIES) for by in pages.values()):
        raise ValueError(f"태그 반영 대상 아님: {sorted(pages)}")
    docs = json.loads(text)["documents"]
    if sorted(d["id"] for d in docs if d["id"] in NEW_DOC_IDS) != sorted(NEW_DOC_IDS):
        raise ValueError("manifest 에 새 3문서가 한 번씩 있지 않음")
    lines = text.splitlines()
    for doc_id in NEW_DOC_IDS:
        hits = [i for i, line in enumerate(lines) if f'"id": "{doc_id}"' in line]
        if len(hits) != 1:
            raise ValueError(f"{doc_id}: 한 줄 한 문서 모양이 아님")
        line = lines[hits[0]]
        comma = "," if line.rstrip().endswith(",") else ""
        try:
            doc = json.loads(line.strip().rstrip(","))
        except json.JSONDecodeError:
            doc = {}
        if not isinstance(doc, dict) or doc.get("id") != doc_id:
            raise ValueError(f"{doc_id}: 한 줄 한 문서 모양이 아님")
        if _protected(doc) or doc.get("typologies"):  # 새 3문서는 쪽 단위만 — 문서 단위 태그가 있으면 거절
            raise ValueError(f"{doc_id}: 원본에 FAN·FX_RELAY·모르는 태그가 있음")
        doc.pop("typology_pages", None)
        if any(pages[doc_id].values()):
            doc["typology_pages"] = {t: list(ps) for t, ps in pages[doc_id].items() if ps}
        lines[hits[0]] = line[: len(line) - len(line.lstrip())] + json.dumps(doc, ensure_ascii=False) + comma
    out = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    _verify(text, out, pages)
    return out


def _protected(doc: Mapping[str, Any]) -> bool:
    keys = {*doc.get("typologies", []), *doc.get("typology_pages", {})}
    return bool({str(k).upper() for k in keys} - set(CORPUS_TYPOLOGIES))


def _verify(before: str, after: str, pages: Mapping[str, Mapping[str, list[int]]]) -> None:
    old = {d["id"]: d for d in json.loads(before)["documents"]}
    new = {d["id"]: d for d in json.loads(after)["documents"]}
    if old.keys() != new.keys():
        raise ValueError("문서 목록이 바뀜")
    for doc_id, d in new.items():
        want = {t: ps for t, ps in pages[doc_id].items() if ps} if doc_id in NEW_DOC_IDS else None
        ok = d.get("typology_pages") == (want or None) if doc_id in NEW_DOC_IDS else d == old[doc_id]
        if not ok:
            raise ValueError(f"{doc_id}: 반영 결과가 요청과 다름")
    kept = [x for x in before.splitlines() if not any(f'"id": "{i}"' in x for i in NEW_DOC_IDS)]
    if kept != [x for x in after.splitlines() if not any(f'"id": "{i}"' in x for i in NEW_DOC_IDS)]:
        raise ValueError("기존 줄이 바뀜")
