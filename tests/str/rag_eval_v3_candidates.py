"""SCRUM-306 평가 세트 v3 정답 후보 — 청크 × 유형, 위치·출처·등급만(본문 0). docs/str/10 SCRUM-306 줄.

CYCLE·SG·GS = 305 확인 등급 ≥ 1(등급 그대로) · FAN_IN·FAN_OUT = 지금 manifest 태그 청크 전부(등급 빔 — 확인 대상).
`db_tagged` = 지금 DB 태그로 그 유형 필터 검색에 걸리는가(여기 둘 다 True, 합의 태그 새 행은 False).
표본 합의 태그 행은 태깅 뒤에 더함. 위치는 `corpus/pdf/` 재분할(해시 = chunk_id) — DB·검색·LLM 0.
"""

from __future__ import annotations

import json
from typing import Any

from tools.corpus_chunks import resolve_typologies
from tools.rag2_sample import MANIFEST, Span, locate_spans, read_pages

from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR
from tests.str.rag_eval_v3_draw import V3_DIR

CANDIDATES_FILE = V3_DIR / "answer_candidates.json"
GRADES_305 = CORPUS_EVAL_DIR / "answers_corpus.json"
GRADED_TYPES = ("CYCLE", "SCATTER_GATHER", "GATHER_SCATTER")
FAN_TYPES = ("FAN_IN", "FAN_OUT")
SOURCE_305 = "305_확인"
SOURCE_FAN = "FAN_태그"
GRADE_MIN = 1
CANDIDATES_DOC = (
    "SCRUM-306 정답 후보(청크 × 유형) — 위치·출처·등급만, 원문 0. grade null = 확인자(김종민) 확인 대상. "
    "표본 합의 태그 행은 태깅 뒤 더함(consensus_pending)."
)


def _metas() -> list[dict[str, Any]]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["documents"]


def corpus_positions(metas: list[dict[str, Any]]) -> dict[str, tuple[str, Span]]:
    """chunk_id → (doc_id, 위치) — 코퍼스 전체 재분할."""
    out: dict[str, tuple[str, Span]] = {}
    for meta in metas:
        for cid, span in locate_spans(meta["id"], read_pages(meta)).items():
            out[cid] = (meta["id"], span)
    return out


def _row(cid: str, where: tuple[str, Span], source: str, grade: int | None) -> dict[str, Any]:
    doc, span = where
    return {
        "chunk_id": cid,
        "doc_id": doc,
        "page": span.page,
        "pos": span.pos,
        "source": source,
        "grade": grade,
        "db_tagged": True,  # 지금 DB 태그로 그 유형 필터 검색에 걸림 — 합의 태그 새 행은 False
    }


def build_candidates(metas: list[dict[str, Any]], grades_305: dict[str, list[dict]]) -> dict[str, list[dict]]:
    pos = corpus_positions(metas)
    by_id = {m["id"]: m for m in metas}
    out: dict[str, list[dict]] = {}
    for typ in FAN_TYPES:
        tagged = [c for c, (doc, s) in pos.items() if typ in resolve_typologies(by_id[doc], s.page)]
        out[typ] = [_row(c, pos[c], SOURCE_FAN, None) for c in tagged]
    for typ in GRADED_TYPES:
        missing = [r["chunk_id"] for r in grades_305[typ] if r["chunk_id"] not in pos]
        if missing:
            raise ValueError(f"{typ}: 305 등급 청크가 재분할에 없음 {len(missing)}")
        out[typ] = [_row(r["chunk_id"], pos[r["chunk_id"]], SOURCE_305, r["grade"])
                    for r in grades_305[typ] if r["grade"] >= GRADE_MIN]  # fmt: skip
    return {t: sorted(rows, key=lambda r: (r["doc_id"], r["page"], r["pos"])) for t, rows in out.items()}


def main() -> None:
    """초안은 파일이 없을 때만 씀 — 있으면 확인 반영(등급·합의 행)이 지워지므로 거절. 재현 검사는 테스트가 메모리에서."""
    if CANDIDATES_FILE.exists():
        raise SystemExit(
            f"{CANDIDATES_FILE.name} 이 이미 있음 — 확인 반영을 지우지 않음(새로 만들려면 사람이 먼저 옮김)"
        )
    grades = json.loads(GRADES_305.read_text(encoding="utf-8"))
    doc = {"_doc": CANDIDATES_DOC, "grades_305": {"checked_by": grades["checked_by"], "checked_at": grades["checked_at"]},
           "consensus_pending": True, "candidates": build_candidates(_metas(), grades["grades"])}  # fmt: skip
    with CANDIDATES_FILE.open("x", encoding="utf-8") as f:
        f.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    print({t: len(rows) for t, rows in doc["candidates"].items()})


if __name__ == "__main__":
    main()
