"""SCRUM-305 holdout_v2 검색 시작 문 (docs/str/10 "305 실행 기록" — 추가 검토 3). DB·검색 0, git 만.

1. 질의 스냅샷 — 질의 파일을 한 번 읽어 304 고정 정규화 해시와 대조(id 만 바꿔도 거절)
2. 커밋된 예약 — `git show HEAD:<원장>` 에 같은 예약 줄(세트·실행 전 고정값·등급표 해시), 작업 트리 원장의 이 세트 줄은
   예약 한 줄뿐(빈 원장 복원·중단 뒤면 거절)
3. 검색 표식 — git ref `refs/holdout-v2/<세트 앞 16>` 을 없을 때만 원자적으로 만듦. 같은 클론의 작업 트리가 공유하고
   원장 파일 복원과 무관 → 새 작업 트리·다시 돌리기 거절
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from tests.str import rag_eval_corpus_ledger as cl
from tests.str.rag_eval_corpus_guard import normalized_sha256

QUERIES_SHA256 = cl.QUERIES_SHA256  # 304 고정값 — 원장 모듈 하나에 둠(test_rag_eval_corpus_set 과 대조)
REF_PREFIX = "refs/holdout-v2/"
ZERO_OID = "0" * 40
NOT_COMMITTED = "예약 줄이 git HEAD 에 커밋돼 있지 않음 — reserve 뒤 원장 파일을 커밋하고 다시"
NOT_RESERVED_HERE = "작업 트리 원장의 이 세트 줄이 예약 한 줄이 아님(빈 원장 복원·중단 뒤) — 검색 안 함"
MISMATCH = "지금 실행 전 고정값·등급표 해시가 커밋된 예약 줄과 다름 — 검색 안 함"
ALREADY_SEARCHED = "이 세트는 이미 검색을 시작한 표식(git ref)이 있음 — 다시 못 돌림"


def queries_snapshot(eval_dir: Path) -> list[dict[str, Any]]:
    """질의 목록을 한 번 읽어 304 고정 해시와 대조 — 다르면 ValueError. 검색·판정은 이 값으로."""
    queries = json.loads((eval_dir / cl.HOLDOUT_QUERIES).read_text(encoding="utf-8"))["queries"]
    if normalized_sha256(queries) != QUERIES_SHA256:
        raise ValueError("holdout_v2 질의 목록이 304 고정값과 다름(id·문자열·순서) — 예약·검색 안 함")
    return queries


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


def _reserved(lines: list[str], set_sha: str) -> list[dict[str, Any]]:
    out = []
    for line in filter(str.strip, lines):
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("set_sha256") == set_sha:
            out.append(e)
    return out


def open_search(repo: Path, rel_eval_dir: Path, pre_sha256: str, grades_sha256: str) -> str | None:
    """검색 시작 허가 — 통과하면 None(표식 ref 를 만든 뒤), 아니면 거절 이유(표식 안 남김)."""
    eval_dir = repo / rel_eval_dir
    set_sha = cl.set_sha256(eval_dir)
    local = _reserved((eval_dir / cl.LEDGER_NAME).read_text(encoding="utf-8").splitlines(), set_sha)
    if [e.get("status") for e in local] != ["reserved"]:
        return NOT_RESERVED_HERE
    head = _git(repo, "show", f"HEAD:{(rel_eval_dir / cl.LEDGER_NAME).as_posix()}")
    committed = _reserved(head.stdout.splitlines(), set_sha) if head.returncode == 0 else []
    if committed != local:
        return NOT_COMMITTED
    if (local[0]["pre_sha256"], local[0]["grades_sha256"]) != (pre_sha256, grades_sha256):
        return MISMATCH
    made = _git(repo, "update-ref", f"{REF_PREFIX}{set_sha[:16]}", "HEAD", ZERO_OID)  # 없을 때만 — 원자적
    return None if made.returncode == 0 else ALREADY_SEARCHED


def open_search_in(eval_dir: Path, pre_sha256: str, grades_sha256: str) -> str | None:
    """`eval_dir` 가 든 git 리포를 찾아 `open_search` — git 리포가 아니면 커밋된 예약 줄이 없는 것."""
    top = _git(eval_dir, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return NOT_COMMITTED
    repo = Path(top.stdout.strip()).resolve()
    return open_search(repo, eval_dir.resolve().relative_to(repo), pre_sha256, grades_sha256)
