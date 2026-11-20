"""SCRUM-305 실행 전 점검·복원 확인·참고 기록 (docs/str/10 "305 실행 기록"). 순수 함수 — DB·검색 0.

- 새 3문서 FAN_IN·FAN_OUT 태그 0: manifest 점검(테스트) + DB 집계 점검(실행 도구가 예약 전에)
- 실행 전 고정값 `PreRun`: 유형별 태그 청크 수 + 확인 완료(그 유형으로 태그된 청크 전부를 확인자가 등급) — 확인 단위 청크 × 유형
- 복원 확인: 청크 수·유형별 태그 수·manifest 해시가 304 때 값과 같은지
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import combinations
from typing import Any

from tests.str.rag_eval_corpus_guard import JUDGED_TYPOLOGIES, TAGGED_KEYS, PreRun, Run, normalized_sha256

NEW_DOC_IDS = ("fincen-cmln-2025", "fintrac-underground-banking-2023", "apg-typologies-2025")
FAN_TAGS = frozenset(("FAN_IN", "FAN_OUT"))
# 304 때 코퍼스(docs/str/10 "코퍼스 크기" 11/18 · manifest @02bcd88b) — 복원하면 이 값으로 돌아와야 함
BASELINE_CHUNKS = 425
BASELINE_TAGGED = {
    "FAN_IN": 19,
    "FAN_OUT": 6,
    "CYCLE": 2,
    "SCATTER_GATHER": 0,
    "GATHER_SCATTER": 0,
    "FX_RELAY": 0,
}
BASELINE_MANIFEST_SHA256 = "02bcd88b5c9890f9ca56277b67022e8253f06e05f5b4d3d2821a6aa49bfcdd7c"


def manifest_fan_problems(manifest: Mapping[str, Any]) -> list[str]:
    """새 3문서의 `typologies`·`typology_pages` 에 FAN 태그(대소문자 무관)가 있으면 문제."""
    out: list[str] = []
    for doc in manifest.get("documents", []):
        if doc.get("id") not in NEW_DOC_IDS:
            continue
        tags = [*doc.get("typologies", []), *doc.get("typology_pages", {})]
        bad = sorted({t for t in tags if str(t).upper() in FAN_TAGS})
        if bad:
            out.append(f"{doc['id']}: FAN 태그 {bad}")
    return out


def preflight_problems(*, new_doc_fan: int, tagged: Mapping[str, int]) -> list[str]:
    """실행 도구가 예약 전에 — DB 에서 새 3문서 청크의 FAN 태그 수 · 유형별 태그 수 칸."""
    out = [f"새 3문서 청크에 FAN 태그 {new_doc_fan}개 — 0 이어야 함"] if new_doc_fan else []
    if set(tagged) != TAGGED_KEYS:
        out.append(f"유형별 태그 수 칸이 다름: {sorted(tagged)}")
    return out


def grades_sha256(doc: Mapping[str, Any]) -> str:
    """확인자 등급 파일(스냅샷)의 정규화 sha256 — 예약 줄에 고정, 판정·재판정 때 대조(추가 검토 1)."""
    return normalized_sha256(dict(doc))


def grade_table(doc: Mapping[str, Any]) -> dict[tuple[str, str], int]:
    """확인자 등급 파일 → {(유형, chunk_id): 등급}. 확인자 이름이 없으면 빈 표(확인 안 끝남)."""
    if not str(doc.get("checked_by", "")).strip():
        return {}
    return {(t, g["chunk_id"]): int(g["grade"]) for t, rows in doc.get("grades", {}).items() for g in rows}


def pre_run(tagged_ids: Mapping[str, Iterable[str]], grades_doc: Mapping[str, Any]) -> PreRun:
    """유형별 태그 청크 수(DB) + 확인 완료 = 그 유형으로 태그된 청크 전부가 확인자 등급표에 있음."""
    ids = {t: set(tagged_ids.get(t, ())) for t in TAGGED_KEYS}
    graded = grade_table(grades_doc)
    has_checker = bool(graded) or bool(str(grades_doc.get("checked_by", "")).strip())
    checked = {t: has_checker and all((t, c) in graded for c in ids[t]) for t in JUDGED_TYPOLOGIES}
    return PreRun(tagged={t: len(v) for t, v in ids.items()}, checked=checked)


def restore_problems(chunks: int, tagged: Mapping[str, int], manifest_sha256: str) -> list[str]:
    out = [f"청크 {chunks} ≠ {BASELINE_CHUNKS}"] if chunks != BASELINE_CHUNKS else []
    diff = {t: (tagged.get(t, 0), n) for t, n in BASELINE_TAGGED.items() if tagged.get(t, 0) != n}
    if diff:
        out.append(f"유형별 태그 수 다름 (지금, 304): {diff}")
    if manifest_sha256 != BASELINE_MANIFEST_SHA256:
        out.append("manifest 해시가 304 때와 다름 — git 으로 되돌림")
    return out


def top3_jaccard(runs: Iterable[Run]) -> dict[str, float]:
    """유형별 질의 쌍의 top-3 겹침 평균(참고 기록). 질의 2개 미만 유형은 뺌."""
    by: dict[str, list[set[str]]] = {}
    for r in runs:
        if r.typology:
            by.setdefault(r.typology, []).append(set(r.top[:3]))
    out = {}
    for t, tops in by.items():
        pairs = [len(a & b) / len(a | b) if a | b else 1.0 for a, b in combinations(tops, 2)]
        if pairs:
            out[t] = round(sum(pairs) / len(pairs), 4)
    return out


def grade0_ratio(
    tagged_ids: Mapping[str, Iterable[str]], grades: Mapping[tuple[str, str], int]
) -> dict[str, float]:
    """태그된 청크 중 확인자 등급 0 비율(유형별, 참고 기록 — 쪽 단위 태그의 크기). 등급 없는 청크 = 0."""
    out = {}
    for t, ids in tagged_ids.items():
        ids = list(ids)
        if ids:
            out[t] = round(sum(grades.get((t, c), 0) == 0 for c in ids) / len(ids), 4)
    return out


def fan_hit_at3(tops: list[list[str]], grades: list[Mapping[str, int]]) -> float:
    """D07~D10 확장 뒤(또는 복원 뒤) hit@3 — top-3 안 준혁 등급 ≥ 1 청크가 있는 질의 비율."""
    return sum(any(g.get(c, 0) >= 1 for c in top[:3]) for top, g in zip(tops, grades, strict=True)) / len(
        tops
    )


def run_notes(
    runs: list[Run], ids: Mapping[str, Iterable[str]], grades: Mapping[tuple[str, str], int], top_k: int
) -> dict:
    """참고 기록(판정에 안 씀) — top-3 겹침 · 태그 청크 등급 0 비율 · top-k 미만 유형."""
    short = sorted({r.typology for r in runs if r.typology and len(r.top) < top_k})
    return {
        "top3_jaccard": top3_jaccard(runs),
        "grade0_ratio": grade0_ratio(ids, grades),
        "under_top_k": short,
    }
