"""SCRUM-306 ★B-4 새 3문서 층 10행 — `docs/str/rag2/03_sampling.md` 1절 4층 · 2절 4번 · 3절.

모집단 = `corpus/pdf/` 재분할 + manifest `typology_pages` 로 태그 없는 청크(DB 무태그 259 와 같음). `02` 를 쓰지 않음.
시드 306 한 난수열을 문서 사전순으로 이어 씀. 기존 70행(`rag2_sample`) 뒤에 덧붙여 `05_sample.csv` 80행.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import tempfile
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from tools.corpus_chunks import resolve_typologies
from tools.rag2_sample import (
    CORPUS_DIR,
    DOC_MIN,
    MANIFEST,
    SAMPLE_CSV,
    SAMPLE_TARGET,
    ReviewRow,
    _round_half_up,
    attach_spans,
    build_sample,
    locate_spans,
    read_pages,
    render_sample,
)

NEW_DOCS = ("apg-typologies-2025", "fincen-cmln-2025", "fintrac-underground-banking-2023")
NEW_SEED = 306
NEW_TARGET = 10
NEW_LARGEST_DOC = "apg-typologies-2025"  # 반올림 차이를 맞추는 문서(03 2절 4번)
FROZEN_70_SHA256 = (
    "773ba999406a1537eb33536c8cbf860db7ab39a4b4ca0b1715ffe5e17a923d07"  # ★B 때 70행 파일(머리글 포함)
)

PagesOf = Callable[[dict], list[str]]


def _metas(manifest: Path = MANIFEST) -> dict[str, dict]:
    return {m["id"]: m for m in json.loads(manifest.read_text(encoding="utf-8"))["documents"]}


def new_population(metas: dict[str, dict], pages_of: PagesOf) -> tuple[list[ReviewRow], dict]:
    """새 3문서의 태그 없는 청크 — (행, 문서별 위치표). 후보·검토 칸은 없음(False)."""
    rows, spans = [], {}
    for doc in NEW_DOCS:
        spans[doc] = locate_spans(doc, pages_of(metas[doc]))
        rows += [ReviewRow(cid, doc, s.page, s.pos, False, False)
                 for cid, s in spans[doc].items() if not resolve_typologies(metas[doc], s.page)]  # fmt: skip
    return rows, spans


def allocate_new(rows: list[ReviewRow]) -> dict[str, int]:
    """문서 → 뽑을 수: 청크 수 비율 · 문서마다 최소 2 · 사사오입 · 차이는 가장 큰 문서에서."""
    counts = {d: sum(r.doc_id == d for r in rows) for d in NEW_DOCS}
    total = sum(counts.values())
    quota = {d: min(n, max(_round_half_up(NEW_TARGET * n / total), DOC_MIN)) for d, n in counts.items()}
    quota[NEW_LARGEST_DOC] += NEW_TARGET - sum(quota.values())
    return quota


def draw_new(rows: list[ReviewRow], quota: dict[str, int], seed: int = NEW_SEED) -> list[ReviewRow]:
    rng = random.Random(seed)
    picked: list[ReviewRow] = []
    for doc in sorted(quota):
        pool = sorted((r for r in rows if r.doc_id == doc), key=lambda r: r.chunk_id)
        picked += rng.sample(pool, quota[doc])
    return sorted(picked, key=lambda r: (r.doc_id, r.page, r.pos))


def build_new(manifest: Path = MANIFEST, corpus_dir: Path = CORPUS_DIR) -> list[dict]:
    metas = _metas(manifest)
    rows, spans = new_population(metas, lambda m: read_pages(m, corpus_dir))
    return attach_spans(draw_new(rows, allocate_new(rows)), spans)


def write_80(rows: list[dict], path: Path = SAMPLE_CSV) -> str:
    """05 쓰기 — 고유 80행 · 앞 70행 동결 해시 · 기존 파일과 다르면 중단 · 없을 때만 원자 교체. 돌려주는 값 = 한 일."""
    text = render_sample(rows)
    lines = text.splitlines(keepends=True)
    if len(rows) != SAMPLE_TARGET + NEW_TARGET or len({r["chunk_id"] for r in rows}) != len(rows):
        raise ValueError(f"고유 {SAMPLE_TARGET + NEW_TARGET}행이 아님 — 05 그대로")
    if sha256("".join(lines[: 1 + SAMPLE_TARGET]).encode()).hexdigest() != FROZEN_70_SHA256:
        raise ValueError("앞 70행이 동결 해시와 다름 — 05 그대로")
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError("기존 05 와 내용이 다름 — 덮지 않음(바꾸려면 사람이 먼저 옮김)")
        return "same"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)
    return "wrote"


def main() -> None:
    parser = argparse.ArgumentParser(description="SCRUM-306 표본 80 = 기존 70 + 새 3문서 10 (03 3절)")
    parser.add_argument("--write", action="store_true", help="05_sample.csv 를 씀(없으면 대조만)")
    args = parser.parse_args()
    rows = build_sample() + build_new()
    if args.write:
        print(f"{write_80(rows)} {len(rows)} rows")
        return
    with SAMPLE_CSV.open(encoding="utf-8", newline="") as f:
        same = [{k: str(v) for k, v in r.items()} for r in rows] == list(csv.DictReader(f))
    print(f"rows {len(rows)} · 05 same={same}")
    raise SystemExit(0 if same else 1)


if __name__ == "__main__":
    main()
