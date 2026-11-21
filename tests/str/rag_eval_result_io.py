"""판정 결과 파일 보호 (SCRUM-308-2 추가 검토 1) — 결과 경로별 실행 잠금 + 임시 파일 → 원자적 게시(기존 결과 안 덮음).

잠금 `<결과>.lock` 은 배타 생성 — 있으면 다른 실행 중이거나 지난 실행이 남긴 것(사람이 확인 뒤 지우고 사유 기록).
게시는 같은 폴더 임시 파일에 다 쓰고 fsync 한 뒤 `os.link` — 결과가 이미 있으면 실패(덮어쓰기 0), 잘린 JSON 이 안 남음.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class ResultLocked(RuntimeError):
    """결과 경로 잠금이 이미 있음."""


def lock_path(out: Path) -> Path:
    return out.with_name(out.name + ".lock")


@contextmanager
def run_lock(out: Path) -> Iterator[None]:
    try:
        fd = os.open(lock_path(out), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        raise ResultLocked(
            f"실행 잠금이 있음({lock_path(out).name}) — 다른 실행 중이거나 지난 실행이 남김"
        ) from None
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        lock_path(out).unlink(missing_ok=True)


def publish_new(out: Path, text: str) -> None:
    """임시 파일에 다 쓰고 fsync → `os.link` 로 게시. 결과가 이미 있으면 FileExistsError(덮어쓰기 0)."""
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)
