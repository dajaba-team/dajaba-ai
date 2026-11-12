"""SCRUM-126 ★L-1 — RAG 검색 평가 (손 실행, pytest 수집 X).

질의 10개 → 실제 `Retriever.retrieve(facts)` → top-3 · 유형별 엄격·넓은 지표 · overlap · Jaccard.

규칙 (지시서):
- 질의는 `facts_fan_in.json` 복사본에서 `typology`·`model_signals`·`customer.industry` 만 바꾼 Facts
- 검색은 실제 `Retriever` 그대로 (build_query·relaxed_order·RAG_CANDIDATES 안 건드림)
- `MIN_SIMILARITY` 는 측정 때만 0.0 으로 **런타임 override** (상수 자체는 안 바꿈)
- top-3 score 를 다 남겨 0.2·0.25·0.3 은 재계산
- 본문 text 는 결과 JSON 에 넣지 않음 (관문 6)

사용 (★L-1 진희 터미널, `AI_LLM_MOCK=false`·`RAG_ENABLED=true`):
    uv run --frozen --extra dev python -m tests.str.rag_eval_live
결과 → `tests/str/recorded/_tmp/rag_eval_SCRUM-126_<stamp>.json`

조립 로직은 `rag_eval_live_support.py` 로 분리 — 파일 길이 가드.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from aml_ai.shared.config import get_settings
from aml_ai.shared.db import get_engine
from tests.str.rag_eval_live_support import (
    assemble_queries_out,
    metrics_for_threshold,
    overlap_and_jaccard,
    retrieval_version,
    retrieve_all,
    verify_expected,
)

REPO = Path(__file__).resolve().parents[2]
EVAL = REPO / "tests" / "str" / "retrieval_eval.json"
TMP_DIR = REPO / "tests" / "str" / "recorded" / "_tmp"


def main() -> int:
    eval_data = json.loads(EVAL.read_text(encoding="utf-8"))
    settings = get_settings()
    session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    with session_factory() as session:
        verify_expected(session, eval_data["expected_sets"])
        all_results = retrieve_all(eval_data, session, settings)
        overlap = overlap_and_jaccard(all_results, session)  # 전문 재조회 — DB 세션 안에서

    result = {
        "retrieval_version": retrieval_version(settings),
        "embedding_model": settings.embedding_model,
        "queries": assemble_queries_out(all_results, eval_data),
        "metrics_by_threshold": {
            str(v): metrics_for_threshold(all_results, eval_data, v) for v in (0.0, 0.2, 0.25, 0.3)
        },
        "overlap": overlap,
    }

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_path = TMP_DIR / f"rag_eval_SCRUM-126_{stamp}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[rag_eval] saved → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
