"""SCRUM-306 받은 시트 판독 · 출력 경로 공통 (`docs/str/rag2/03_sampling.md` 5절 · 추가 검토 1회차).

- 판독: 태깅·결정·등급 시트 모두 같은 함수 — UTF-8(BOM 허용) · 행마다 셀 수 = 머리글 칸 수(쉼표로 칸이 밀린 행 거절).
- 출력: 실제 경로가 어느 Git 작업 트리에도 속하지 않아야 하고, 새 파일로만 만든다(있으면 거절).
- 확인자 폴더: Git 작업 트리 밖 · `blind_*` 아님 · 허락한 파일 말고 다른 파일이 없어야 함.
"""

from __future__ import annotations

import csv
import subprocess
from collections.abc import Iterable
from pathlib import Path

BLIND_PREFIX = "blind_"
IGNORED_FILES = {".DS_Store"}  # macOS 가 폴더를 열면 만드는 파일


class SheetError(ValueError):
    """받은 시트 거절 — 문제를 모두 모아 한 번에."""


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    """(머리글, 행 목록) — 셀 수가 머리글과 다른 행이 하나라도 있으면 SheetError."""
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            table = list(csv.reader(f))
    except UnicodeDecodeError as exc:
        raise SheetError(f"{path.name}: UTF-8 이 아님 — CSV UTF-8 로 저장해 주세요") from exc
    if not table:
        raise SheetError(f"{path.name}: 빈 파일")
    fields, body = table[0], table[1:]
    bad = [
        f"{i}행 셀 {len(r)} ≠ 머리글 {len(fields)}"
        for i, r in enumerate(body, start=2)
        if len(r) != len(fields)
    ]
    if bad:
        raise SheetError(f"{path.name}: " + " · ".join(bad[:10]))
    return fields, [dict(zip(fields, r, strict=True)) for r in body]


def in_worktree(path: Path) -> bool:
    """실제 경로(심볼릭 링크 푼 뒤)가 Git 작업 트리 안인가 — 아직 없는 경로는 있는 가장 가까운 상위로 판단."""
    probe = Path(path).expanduser().resolve()
    while not probe.is_dir():
        probe = probe.parent
    done = subprocess.run(["git", "-C", str(probe), "rev-parse", "--is-inside-work-tree"],
                          capture_output=True, text=True, check=False)  # fmt: skip
    return done.returncode == 0 and done.stdout.strip() == "true"


def write_new(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Git 작업 트리 밖에 새 파일로만 씀 — 있으면(manifest·받은 시트 포함) 바이트 그대로 두고 거절."""
    if in_worktree(path):
        raise ValueError(f"Git 작업 트리 안 — 리포 밖에만 씀: {Path(path).name}")
    try:
        with Path(path).open("x", encoding=encoding, newline="") as f:
            f.write(text)
    except FileExistsError as exc:
        raise ValueError(f"이미 있음 — 덮지 않음: {Path(path).name}") from exc


def out_dir_problem(out_dir: Path, allowed: Iterable[str]) -> str | None:
    """확인자 폴더 검사 — 문제 한 줄, 없으면 None. 본문을 쓰기 전에 부른다."""
    if "~" in Path(out_dir).parts:  # 셸이 풀지 않은 ~ (따옴표 안) — 풀면 엉뚱한 홈 폴더에 씀
        return "--out 에 풀리지 않은 ~ 가 있음 — 절대 경로로"
    out_dir = Path(out_dir)
    if in_worktree(out_dir):
        return "--out 이 Git 작업 트리 안 — 본문이 든 시트는 리포 밖 폴더에만"
    blind = [
        part for part in out_dir.resolve().parts if part.lower().startswith(BLIND_PREFIX)
    ]  # 대소문자 무시(macOS)
    if blind:
        return f"--out 이 블라인드 묶음 폴더({blind[0]}) 안 — 확인자 폴더를 따로"
    extra = (
        sorted({p.name for p in out_dir.iterdir()} - set(allowed) - IGNORED_FILES) if out_dir.is_dir() else []
    )
    return f"--out 에 확인자 단계 파일이 아닌 것이 있음: {extra[:5]}" if extra else None


def place_problem(path: Path, text: str | None) -> str | None:
    """목적지 사전 검사 — text 가 None 이면 새로 만들 CSV(없어야 함), 있으면 안내 파일(없거나 같은 내용일 때만)."""
    path = Path(path)
    if path.is_symlink():
        return f"{path.name}: 심볼릭 링크 — 거절"
    if not path.exists():
        return None
    if text is None:
        return f"{path.name} 이 이미 있음 — 덮지 않음"
    return (
        None if path.read_text(encoding="utf-8") == text else f"{path.name} 이 기대 내용과 다름 — 덮지 않음"
    )


def place_text(path: Path, text: str) -> None:
    """place_problem 을 통과한 안내 파일 — 없으면 배타 생성, 같은 내용이면 그대로."""
    if not Path(path).exists():
        with Path(path).open("x", encoding="utf-8") as f:
            f.write(text)


def merged_note(path: Path, section: str, mark: str) -> str:
    """단계별 README — 이미 있는 절은 그대로 두고 그 단계 절(mark)이 없을 때만 덧붙인 글."""
    old = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
    return old if mark in old else old + section
