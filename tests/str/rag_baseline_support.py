"""SCRUM-146 기준선 하네스 순수 도우미 (docs/str/10 "기준선"). DB·임베딩 0 — 하네스(`rag_baseline_live`)가 씀.

청크 기록 칸 = chunk_id · doc_id · page · seq(쪽 안 순번) · lang. **원문 지문은 안 남김**(공개 문서 이용 조건 —
FATF 자료 무단 복제 불가 고지). seq = 같은 doc_id·page 안에서 적재 순서(적재 도구와 같은 청크 나누기 출력 순서) 몇 번째.
"""

from __future__ import annotations

from collections.abc import Mapping
from statistics import quantiles
from typing import Any

ALLOWED_KINDS: tuple[tuple[str, ...], ...] = (("a",), ("a", "c"), ("a", "b", "c"))


def page_seq(load_order: list[tuple[str, int, str]]) -> dict[str, int]:
    """적재 순서 [(doc_id, page, chunk_id), ...] → {chunk_id: 같은 doc_id·page 안 1부터 순번}.
    같은 chunk_id 가 다시 나오면(적재 때 ON CONFLICT 로 빠진 것) 처음 순번만, 뒤 것은 셈에서 뺌."""
    counts: dict[tuple[str, int], int] = {}
    seq: dict[str, int] = {}
    for doc_id, page, cid in load_order:
        if cid not in seq:
            key = (doc_id, page)
            counts[key] = counts.get(key, 0) + 1
            seq[cid] = counts[key]
    return seq


def chunk_ref(row: Mapping[str, Any], seq: Mapping[str, int]) -> dict[str, Any]:
    """{chunk_id, doc_id, page, seq, lang} — seq 에 없으면 None. text 칸은 받아도 안 씀."""
    return {
        **{key: row[key] for key in ("chunk_id", "doc_id", "page", "lang")},
        "seq": seq.get(row["chunk_id"]),
    }


def parse_kinds(arg: str) -> tuple[str, ...]:
    """'a' · 'a,c' · 'a,b,c' 만 받음(공백 무시). 그 밖은 ValueError."""
    kinds = tuple(part.strip() for part in arg.split(","))
    if kinds not in ALLOWED_KINDS:
        raise ValueError("kinds must be a, a,c or a,b,c")
    return kinds


def recall_at(top_ids: list[str], expected: set[str], k: int) -> float:
    """|기대 ∩ top_ids[:k]| ÷ |기대|. 기대가 비면 0.0."""
    return len(set(top_ids[:k]) & expected) / len(expected) if expected else 0.0


def rank_of(ranking: list[str], chunk_id: str) -> int | None:
    """1부터 순위. 없으면 None."""
    return ranking.index(chunk_id) + 1 if chunk_id in ranking else None


def cosine_summary(values: list[float]) -> dict[str, Any]:
    """{n, min, p25, median, p75, max} — 사분위는 선형 보간(statistics.quantiles method='inclusive'), 반올림 6자리.
    빈 목록이면 n 0 · 나머지 None. 값이 하나면 다섯 칸 모두 그 값."""
    keys = ("min", "p25", "median", "p75", "max")
    if not values:
        return {"n": 0, **dict.fromkeys(keys)}
    quartiles = quantiles(values, n=4, method="inclusive") if len(values) > 1 else values * 3
    summary = [min(values), *quartiles, max(values)]
    return {"n": len(values), **{key: round(value, 6) for key, value in zip(keys, summary, strict=True)}}


def ab_overlap(a_top: list[str], b_top: list[str], expected: set[str]) -> dict[str, list[str]]:
    """(a)·(b) top 겹침을 정답 / 오답으로 — {"correct": [...], "wrong": [...]}, 각각 오름차순."""
    common = set(a_top) & set(b_top)
    return {"correct": sorted(common & expected), "wrong": sorted(common - expected)}


def lang_count(top: list[Mapping[str, Any]], lang: str) -> int:
    return sum(row.get("lang") == lang for row in top)
