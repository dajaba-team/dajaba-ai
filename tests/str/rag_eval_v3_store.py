"""SCRUM-306 `answer_candidates.json` 반영 공통 — 잠금 하나 · 임시 파일 원자 교체 (추가 검토 1회차).

반영 둘(`apply-fan` · `apply`)은 같은 잠금을 잡고 그 안에서 최신 파일을 읽어 단계 순서를 검사한 뒤 쓴다.
쓰기는 같은 폴더 임시 파일 → `os.replace` 라 중간에 끊겨도 반쪽 JSON 이 남지 않는다.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any

BUSY = "다른 반영이 진행 중(잠금) — 끝난 뒤 다시"


class Busy(RuntimeError):
    """같은 후보 파일에 다른 반영이 잠금을 잡고 있음."""


def lock_path(target: Path) -> Path:
    """잠금 파일은 리포 밖(임시 폴더) — 후보 파일 실제 경로로 이름을 정함."""
    key = sha256(str(Path(target).resolve()).encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / f"rag_eval_v3_{key}.lock"


@contextmanager
def locked(target: Path) -> Iterator[None]:
    with lock_path(target).open("w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Busy(BUSY) from exc
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def atomic_write(target: Path, doc: dict[str, Any]) -> None:
    target = Path(target)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
