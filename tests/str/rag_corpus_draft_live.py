"""SCRUM-305 태그 후보 초벌 (손 실행, pytest 수집 X — 진희 터미널, 호스트에서. docs/str/10 "305 실행 기록" 태그 도구).

    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_corpus_draft_live --limit 3
    PYTHONPATH=. uv run --frozen --extra dev python -m tests.str.rag_corpus_draft_live

DB 의 새 3문서 청크(읽기 전용)만 × CYCLE·SCATTER_GATHER·GATHER_SCATTER 로 LLM 에 등급(0·1·2)만 물음 — 프롬프트
`tools/prompts/rag_answer_v2.md`, 호출은 275 초벌과 같은 함수(`rag_answer_draft_live.ask`). 청크 본문을 외부 LLM 에 보냄
(09 2026-11-19, 이용 조건 ⑤와 같은 처리). 결과 `answer_draft_corpus.json` 에는 chunk_id·doc_id·page·grade 만. 이미 있으면
덮지 않음(`--limit` 시험 실행은 `_limit` 파일 — 같은 규칙). 전체 실행은 새 3문서가 34·17·246 으로 다 적재됐을 때만.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

import httpx
from sqlalchemy import bindparam, text

from aml_ai.shared.config import get_settings
from tests.str.rag_answer_draft_live import ask
from tests.str.rag_baseline_live_db import readonly_session
from tests.str.rag_corpus_check import DRAFT_NAME
from tests.str.rag_corpus_tags import draft_doc, loaded_problems
from tests.str.rag_eval_corpus_preflight import NEW_DOC_IDS
from tests.str.rag_eval_corpus_support import CORPUS_EVAL_DIR

REPO = Path(__file__).resolve().parents[2]
PROMPT = REPO / "tools/prompts/rag_answer_v2.md"
DRAFT_FILE = CORPUS_EVAL_DIR / DRAFT_NAME
_NEW_ROWS = text(
    "SELECT chunk_id, doc_id, page, text FROM ai.reference_chunks WHERE doc_id IN :ids ORDER BY doc_id, page, chunk_id"
).bindparams(bindparam("ids", expanding=True))


def new_rows(limit: int | None) -> list[tuple[str, str, int, str]]:
    with readonly_session() as session:
        rows = [
            (r.chunk_id, r.doc_id, r.page, r.text)
            for r in session.execute(_NEW_ROWS, {"ids": list(NEW_DOC_IDS)})
        ]
    return rows[:limit] if limit else rows


def run_draft(
    out: Path,
    rows: list[tuple[str, str, int, str]],
    grade: Callable[[str, str], int],
    *,
    prompt_sha256: str,
    model: str,
    print_: Callable[[str], None] = print,
) -> int:
    """결과 파일이 있으면 거절. LLM 호출 전에 `.running` 표식을 배타 생성(동시 실행 하나만), 완성본은 덮지 않게 게시."""
    running = out.with_name(out.name + ".running")
    if out.exists():
        print_(f"{out.name} 이 이미 있음 — 덮지 않음")
        return 1
    try:
        os.close(os.open(running, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        print_(f"{running.name} 가 있음 — 다른 초벌이 도는 중(멈춘 거면 표식을 지우고 다시)")
        return 1
    try:
        doc = draft_doc(rows, grade, prompt_sha256=prompt_sha256, model=model)
        tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            os.link(tmp, out)  # 이미 있으면 FileExistsError — 덮지 않음
        finally:
            tmp.unlink()
    finally:
        running.unlink()
    positive = {t: sum(1 for r in rs if r["grade"] > 0) for t, rs in doc["graded"].items()}
    print_(f"chunks={doc['chunks']} positive={positive} → {out.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="앞 N 청크만(시험 실행 — _limit 파일)")
    args = parser.parse_args(argv)
    out = DRAFT_FILE if args.limit is None else CORPUS_EVAL_DIR / "answer_draft_corpus_limit.json"
    rows = new_rows(args.limit)
    problems = [] if args.limit else loaded_problems(rows)  # 전체 초벌 전 — 새 3문서 34·17·246 적재 확인
    if problems:
        print("초벌 안 함: " + " · ".join(problems))
        return 2
    settings, system = get_settings(), PROMPT.read_text(encoding="utf-8")
    with httpx.Client(timeout=settings.llm_timeout_s) as http:
        return run_draft(out, rows, lambda chunk, typ: ask(http, settings, system, typ, chunk),
                         prompt_sha256=sha256(PROMPT.read_bytes()).hexdigest(), model=settings.llm_model_judge)  # fmt: skip


if __name__ == "__main__":
    raise SystemExit(main())
