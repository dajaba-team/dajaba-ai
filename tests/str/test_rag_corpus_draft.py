"""SCRUM-305 태그 후보 초벌 결과 파일 (docs/str/10 "305 실행 기록" 태그 도구 ⑥). LLM·DB 0 — 가짜 등급 함수."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from tests.str import rag_corpus_draft_live as dl
from tests.str.rag_eval_corpus_preflight import NEW_DOC_IDS

ROWS = [("a" * 64, NEW_DOC_IDS[2], 5, "t")]


def _run(out: Path, delay: float = 0.0) -> int:
    def grade(_chunk: str, _typ: str) -> int:
        time.sleep(delay)
        return 0

    return dl.run_draft(out, ROWS, grade, prompt_sha256="ab" * 32, model="m", print_=lambda _m: None)


def test_draft_writes_once_and_refuses_existing(tmp_path: Path) -> None:
    out = tmp_path / "answer_draft_corpus_limit.json"
    assert _run(out) == 0 and json.loads(out.read_text(encoding="utf-8"))["chunks"] == 1
    first = out.read_text(encoding="utf-8")
    assert _run(out) == 1 and out.read_text(encoding="utf-8") == first  # 시험 재실행도 덮지 않음
    assert sorted(p.name for p in tmp_path.iterdir()) == [out.name]  # 임시·표식 파일 안 남음


def test_concurrent_drafts_only_one_runs(tmp_path: Path) -> None:
    out = tmp_path / "answer_draft_corpus.json"
    codes: list[int] = []
    threads = [threading.Thread(target=lambda: codes.append(_run(out, delay=0.1))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [0, 1] and out.exists()
