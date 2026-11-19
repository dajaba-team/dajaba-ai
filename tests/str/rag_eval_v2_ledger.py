"""SCRUM-275 보류용 실행 원장 (docs/str/10 "도구" — 추가 검토 2 반영). 덧붙이기만.

`tests/str/rag_eval_v2/holdout_ledger.jsonl` 은 git 추적 파일(빈 파일로 시작) — 지우거나 고치면 git 에 드러남.
예약 = 잠금(flock) 안에서 원장을 읽어 같은 보류용 세트 해시가 없을 때만 한 줄 덧붙임(검색 전). 결과 파일을
지우거나 출력 경로를 바꿔도 원장 줄은 남아 다시 못 돌림. 원장이 없으면 만들지 않고 거절("원장 복구 필요").
줄 = 세트 해시 · 시각 · 상태(reserved → done | aborted)만 — 정답·결과 없음.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

LEDGER_NAME = "holdout_ledger.jsonl"
HOLDOUT_QUERIES = "queries_holdout.json"
MISSING = "보류용 원장이 없음 — 원장 복구 필요(git 에서 tests/str/rag_eval_v2/holdout_ledger.jsonl 되살림)"
USED = "이 보류용 세트는 원장에 이미 있음 — 한 번만 판정(결과 파일을 지워도 다시 못 돌림)"


def set_sha256(eval_dir: Path) -> str:
    return sha256((eval_dir / HOLDOUT_QUERIES).read_bytes()).hexdigest()


def reserve(eval_dir: Path) -> str | None:
    """검색 전에 호출. 통과하면 None(원장에 reserved 한 줄), 아니면 거절 이유."""
    path = eval_dir / LEDGER_NAME
    if not path.is_file():
        return MISSING
    digest = set_sha256(eval_dir)
    with path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        entries = [json.loads(line) for line in fh if line.strip()]
        if any(e.get("set_sha256") == digest for e in entries):
            return USED
        _append(fh, {"set_sha256": digest, "status": "reserved", "at": _now()})
    return None


def record(eval_dir: Path, status: str, **extra: object) -> None:
    """끝(done)·중단(aborted)을 덧붙임. 원장이 없어졌으면 만들지 않음(되살림은 git 으로)."""
    path = eval_dir / LEDGER_NAME
    if not path.is_file():
        return
    with path.open("r+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0, os.SEEK_END)
        _append(fh, {"set_sha256": set_sha256(eval_dir), "status": status, "at": _now(), **extra})


def _append(fh, entry: dict) -> None:  # noqa: ANN001 — 열린 텍스트 파일
    fh.seek(0, os.SEEK_END)
    fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    fh.flush()
    os.fsync(fh.fileno())


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
