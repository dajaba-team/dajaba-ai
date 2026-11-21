"""SCRUM-307 새 거절 검사만 지금 DB·ES 에 대 보기 (손 실행, 추가 검토 2 — 결과 파일·임베딩 0, 읽기 전용).

① 기준 커밋 ② v3 정답 확인·후보 chunk_id 전부 DB·태그 = `db_tagged` ③ ES `_count`(200·샤드 실패 0) = DB
④ `ELASTIC_INDEX` = v2 ⑥ 위치표 — 하네스와 같은 `refuse`(결과 파일 있음 ⑤ 만 건너뜀) → 질의 34 의 키워드 검색 62번을
하네스와 같은 검사 transport 로(200 · `timed_out=false` · 샤드 실패 0) → 읽기 전용 REPEATABLE READ 스냅샷에서 ②⑥ 재확인.
하나라도 걸리면 이유 한 줄 + 종료 코드 1. 검색어 문장·본문 출력 0.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aml_ai.shared.config import get_settings
from aml_ai.str.domain.constants import RAG_CANDIDATES
from aml_ai.str.domain.rag_queries import keyword_queries
from tests.str import rag_eval_v3_hybrid_guard as guard
from tests.str import rag_eval_v3_hybrid_support as hs
from tests.str.rag_eval_v2_support import build_facts
from tests.str.rag_eval_v3_hybrid_es import PartialSearch, checked_keyword_search
from tests.str.rag_eval_v3_hybrid_live import refuse
from tests.str.rag_eval_v3_hybrid_run import snapshot_session


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    settings = get_settings()
    cand, positions = _load(hs.CANDIDATES_FILE), _load(hs.POSITIONS_FILE)
    if reason := refuse(settings, cand, positions, False, None, check_result=False):
        print(f"거절: {reason}")
        return 1
    keyword, calls = checked_keyword_search(settings), 0
    try:
        for query in _load(hs.QUERIES_FILE)["queries"]:
            for kq in keyword_queries(build_facts(query)):
                keyword.search(kq.lang, kq.text, RAG_CANDIDATES)
                calls += 1
    except PartialSearch as exc:
        print(f"거절: ES 부분 응답({exc}) — {calls} 번째 뒤")
        return 1
    with snapshot_session() as session:
        reason, rows = guard.db_problem(session, cand, positions)
    if reason:
        print(f"거절(스냅샷): {reason}")
        return 1
    print(f"통과 — 거절 ①②③④⑥ · ES 키워드 {calls}번 부분 응답 0 · 스냅샷 DB {rows}행 · 결과 파일 안 씀")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
