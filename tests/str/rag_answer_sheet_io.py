"""SCRUM-275-2 정답 두 파일 함께 쓰기 (추가 검토 2 — 하나만 바뀐 채 실패하지 않게).

같은 폴더 임시 파일에 둘 다 완성(fsync) → 기존 파일은 백업(복사) → `os.replace` 로 차례 교체 → 중간 실패면 백업으로
둘 다 되돌리고(없던 파일은 지움) 다시 던짐 → 성공하면 백업 지움. 임시·백업 파일은 어느 쪽이든 남기지 않음.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _temp(target: Path) -> Path:
    return target.with_name(f".{target.name}.tmp")


def _backup(target: Path) -> Path:
    return target.with_name(f".{target.name}.bak")


def _write_temp(path: Path, text: str) -> None:
    with path.open("x", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())


def write_pair(docs: dict[Path, str]) -> None:
    targets = list(docs)
    existed = {t: t.exists() for t in targets}
    replaced: list[Path] = []
    try:
        for target in targets:
            _write_temp(_temp(target), docs[target])
        for target in targets:
            if existed[target]:
                shutil.copy2(target, _backup(target))
        for target in targets:
            os.replace(_temp(target), target)
            replaced.append(target)
    except BaseException:
        for target in replaced:
            if existed[target]:
                os.replace(_backup(target), target)
            else:
                target.unlink(missing_ok=True)
        raise
    finally:
        for target in targets:
            _temp(target).unlink(missing_ok=True)
            _backup(target).unlink(missing_ok=True)
