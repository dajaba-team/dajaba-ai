"""SCRUM-307 위치표 — chunk_id → doc_id · page · 쪽 안 순번 (호스트에서 손 실행, docs/str/10 307 실행 절).

컨테이너엔 PDF·pymupdf 가 없고 305 초벌엔 새 297청크의 순번이 없어서, 판정 실행 전에 호스트에서 한 번 만든다.
`corpus/pdf/` 재분할(306 정답 후보와 같은 `corpus_positions`) · DB 는 읽기 전용으로 chunk_id 만 대조. 본문 0.
파일이 이미 있으면 같은 내용일 때만 "그대로", 다르면 거절(덮어쓰지 않음).
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

from sqlalchemy import text
from tools.rag2_sample import MANIFEST

from tests.str.rag_baseline_live_db import readonly_session
from tests.str.rag_eval_v3_candidates import _metas, corpus_positions
from tests.str.rag_eval_v3_hybrid_guard import positions_problem
from tests.str.rag_eval_v3_hybrid_support import POSITIONS_FILE

POSITIONS_DOC = "SCRUM-307 위치표 — chunk_id → doc_id·page·pos(쪽 안 청크 순번), corpus/pdf 재분할. 본문 0."


def build_positions(found: dict[str, tuple[str, Any]], manifest_sha256: str) -> dict[str, Any]:
    """`corpus_positions` 결과 → 파일 모양(chunk_id 정렬)."""
    return {
        "_doc": POSITIONS_DOC,
        "manifest_sha256": manifest_sha256,
        "positions": {
            cid: {"doc_id": doc, "page": span.page, "pos": span.pos}
            for cid, (doc, span) in sorted(found.items())
        },
    }


def main() -> int:
    doc = build_positions(corpus_positions(_metas()), sha256(MANIFEST.read_bytes()).hexdigest())
    with readonly_session() as session:
        db_ids = set(session.execute(text("SELECT chunk_id FROM ai.reference_chunks")).scalars())
    if reason := positions_problem(doc["positions"], db_ids):
        print(reason)
        return 1
    body = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if POSITIONS_FILE.exists():
        same = POSITIONS_FILE.read_text(encoding="utf-8") == body
        print("위치표 그대로(같은 내용)" if same else "위치표가 이미 있고 내용이 다름 — 덮어쓰지 않음")
        return 0 if same else 1
    POSITIONS_FILE.write_text(body, encoding="utf-8")
    print(f"wrote {len(doc['positions'])} positions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
