"""SCRUM-306 표본 70 — `docs/str/rag2/03_sampling.md` 2·3절 그대로 뽑고 청크 오프셋을 붙임.

사람이 고르지 않음: 시드 281 로 다시 뽑으면 `05_sample.csv` 와 같아야 함(테스트). DB·LLM·검색 0.
원문은 쓰지 않음 — 출력 칸은 chunk_id·doc_id·page·쪽안_청크순번·시작·끝 만.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import random
import unicodedata
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from aml_ai.str.domain.constants import CHUNK_OVERLAP_TOKENS, CHUNK_TOKENS
from tools.corpus_chunks import chunk_pdf_pages, compute_content_hash

ROOT = Path(__file__).resolve().parents[1]
REVIEW_CSV = ROOT / "docs/str/rag2/02_untagged_review.csv"
SAMPLE_CSV = ROOT / "docs/str/rag2/05_sample.csv"
MANIFEST = ROOT / "corpus/manifest.json"
CORPUS_DIR = ROOT / "corpus"

SAMPLE_SEED = 281
SAMPLE_TARGET = 70
CANDIDATE_CAP = 35
DOC_MIN = 2
KO_DOC = "fincen-msb-ko-2007"
KO_DOC_MIN = 4
LARGEST_DOC = "fatf-tbml-2020"  # 반올림 차이를 맞추는 문서(03 2절 3번)
CANDIDATE_COL = "후보유형_AI보조초안_사람확인전"
SAMPLE_FIELDS = ["chunk_id", "doc_id", "page", "쪽안_청크순번", "시작", "끝"]


@dataclass(frozen=True)
class ReviewRow:
    chunk_id: str
    doc_id: str
    page: int
    pos: int
    candidate: bool
    reviewed: bool


@dataclass(frozen=True)
class Span:
    page: int
    pos: int
    start: int
    end: int


def load_review(path: Path = REVIEW_CSV) -> list[ReviewRow]:
    with path.open(encoding="utf-8", newline="") as f:
        return [
            ReviewRow(r["chunk_id"], r["doc_id"], int(r["page"]), int(r["쪽안_청크순번"]),
                      bool(r[CANDIDATE_COL].strip()), r["검토상태"] == "검토")
            for r in csv.DictReader(f)
        ]  # fmt: skip


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def allocate(rows: list[ReviewRow]) -> dict[tuple[str, bool], int]:
    """(doc_id, 후보 있음?) → 뽑을 수. 03 2절 1~3번."""
    counts = Counter((r.doc_id, r.candidate) for r in rows)
    docs = sorted({r.doc_id for r in rows})
    with_candidate = sum(n for (_, cand), n in counts.items() if cand)
    if with_candidate > CANDIDATE_CAP:
        raise ValueError("후보 있음 층이 상한을 넘음 — 03 2절 1번 문서 비율 나눔은 이번 범위 밖")
    quota = {(d, True): counts[(d, True)] for d in docs if counts[(d, True)]}
    rest = SAMPLE_TARGET - with_candidate
    denom = sum(counts[(d, False)] for d in docs)
    for d in docs:
        n = counts[(d, False)]
        floor = KO_DOC_MIN if d == KO_DOC else DOC_MIN
        quota[(d, False)] = min(n, max(_round_half_up(rest * n / denom), floor))
    quota[(LARGEST_DOC, False)] += SAMPLE_TARGET - sum(quota.values())
    return quota


def draw(
    rows: list[ReviewRow], quota: dict[tuple[str, bool], int], seed: int = SAMPLE_SEED
) -> list[ReviewRow]:
    """한 난수열을 층 순서(doc_id 사전순 → 후보 있음 → 없음)대로 이어 씀. 결과는 doc·page·순번 순."""
    rng = random.Random(seed)
    picked: list[ReviewRow] = []
    for doc in sorted({r.doc_id for r in rows}):
        for cand in (True, False):
            pool = sorted(
                (r for r in rows if r.doc_id == doc and r.candidate == cand), key=lambda r: r.chunk_id
            )
            k = quota.get((doc, cand), 0)
            if k:
                picked += rng.sample(pool, k)
    return sorted(picked, key=lambda r: (r.doc_id, r.page, r.pos))


def locate_spans(doc_id: str, pages: list[str]) -> dict[str, Span]:
    """재분할한 청크마다 그 쪽 NFKC 추출문 기준 [시작, 끝) — 잘라 낸 문자열의 해시가 chunk_id 와 같아야 함."""
    out: dict[str, Span] = {}
    norm_pages = [unicodedata.normalize("NFKC", p) for p in pages]
    cursor: dict[int, int] = {}
    seq: Counter[int] = Counter()
    for chunk in chunk_pdf_pages(pages, CHUNK_TOKENS, CHUNK_OVERLAP_TOKENS):
        body = unicodedata.normalize("NFKC", chunk.text).strip()
        start = norm_pages[chunk.page - 1].find(body, cursor.get(chunk.page, 0))
        if start < 0:
            raise ValueError(f"오프셋 못 찾음: {doc_id} p{chunk.page}")
        cursor[chunk.page] = start + 1
        seq[chunk.page] += 1
        end = start + len(body)
        cid = compute_content_hash(doc_id, chunk.page, chunk.text)
        if compute_content_hash(doc_id, chunk.page, norm_pages[chunk.page - 1][start:end]) != cid:
            raise ValueError(f"오프셋 해시 다름: {doc_id} p{chunk.page}")
        out[cid] = Span(chunk.page, seq[chunk.page], start, end)
    return out


def attach_spans(
    picked: list[ReviewRow], spans_by_doc: dict[str, dict[str, Span]]
) -> list[dict[str, object]]:
    """표본 행마다 재분할 결과와 대조 — 하나라도 없거나 쪽·순번이 다르면 멈춤(03 3절)."""
    out = []
    for r in picked:
        span = spans_by_doc.get(r.doc_id, {}).get(r.chunk_id)
        if span is None or (span.page, span.pos) != (r.page, r.pos):
            raise ValueError(f"재분할 해시 불일치: {r.doc_id} p{r.page} #{r.pos}")
        out.append({"chunk_id": r.chunk_id, "doc_id": r.doc_id, "page": r.page,
                    "쪽안_청크순번": r.pos, "시작": span.start, "끝": span.end})  # fmt: skip
    return out


def sample_pdfs_present(sample: Path = SAMPLE_CSV, corpus_dir: Path = CORPUS_DIR) -> bool:
    """표본 문서 PDF 가 다 있나(git 무시 폴더 — CI 에는 없음)."""
    with sample.open(encoding="utf-8", newline="") as f:
        docs = {r["doc_id"] for r in csv.DictReader(f)}
    return all((corpus_dir / "pdf" / f"{d}.pdf").exists() for d in docs)


def read_pages(meta: dict, corpus_dir: Path = CORPUS_DIR) -> list[str]:
    import pymupdf

    path = corpus_dir / "pdf" / f"{meta['id']}.pdf"
    if sha256(path.read_bytes()).hexdigest() != meta["sha256"]:
        raise ValueError(f"PDF sha256 다름: {meta['id']}")
    with pymupdf.open(path) as document:
        if len(document) != meta["pages"]:
            raise ValueError(f"PDF 쪽 수 다름: {meta['id']}")
        return [page.get_text() for page in document]


def build_sample(
    review: Path = REVIEW_CSV, manifest: Path = MANIFEST, corpus_dir: Path = CORPUS_DIR
) -> list[dict]:
    rows = load_review(review)
    picked = draw(rows, allocate(rows))
    metas = {m["id"]: m for m in json.loads(manifest.read_text(encoding="utf-8"))["documents"]}
    spans = {d: locate_spans(d, read_pages(metas[d], corpus_dir)) for d in sorted({r.doc_id for r in picked})}
    return attach_spans(picked, spans)


def render_sample(rows: list[dict]) -> str:
    """05 파일 글자 그대로(머리글 + 행, LF) — 쓰기는 `rag2_sample_new.write_80` 만."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=SAMPLE_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def main() -> None:
    """기존 70행 층만 다시 뽑아 05 앞 70행과 대조 — 쓰기·80행 전체 대조는 `tools.rag2_sample_new --write` 하나."""
    argparse.ArgumentParser(description="SCRUM-306 표본 70 층 대조 (03 3절) — 쓰지 않음").parse_args()
    rows = build_sample()
    with SAMPLE_CSV.open(encoding="utf-8", newline="") as f:
        same = [{k: str(v) for k, v in r.items()} for r in rows] == list(csv.DictReader(f))[:SAMPLE_TARGET]
    print(f"rows {len(rows)} · hash ok {len(rows)}/{len(rows)} · 05 앞 {SAMPLE_TARGET}행 same={same}")
    raise SystemExit(0 if same else 1)


if __name__ == "__main__":
    main()
