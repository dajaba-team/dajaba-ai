"""앱이 실행 중에 읽는 리포 파일이 Docker 이미지에 들어가는지 (SCRUM-256).

Dockerfile 의 `COPY <원본> <대상>` 줄 글자만 읽는다 — Docker 는 실행하지 않는다.
파일 복사(`COPY a/b.json ./a/b.json`)와 디렉터리 복사(`COPY src ./src`) 둘 다 인정.
`src/` 안 파일(prompts·fewshot)은 `COPY src` 로 들어가므로 목록에 안 적는다
(docs/str/10 "코퍼스", 09 2026-11-17 (SCRUM-256)).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"

# 실행 중 읽는 리포 파일 (src/ 밖). 새로 생기면 여기에 추가
RUNTIME_FILES = (
    "contracts/display_labels_v1.json",  # str/infrastructure/display_labels.py
    "corpus/manifest.json",  # shared/versioning.py retrieval_version()
)

# 이미지에 들어가면 안 되는 경로 (.gitignore — 저작권·용량)
FORBIDDEN = ("corpus/pdf",)


def copy_sources(text: str) -> list[PurePosixPath]:
    """`COPY` 줄의 원본 경로들 (마지막 인자 = 대상은 뺌, `--flag` 는 무시)."""
    out: list[PurePosixPath] = []
    for line in text.splitlines():
        parts = line.split()
        if not parts or parts[0].upper() != "COPY":
            continue
        args = [p for p in parts[1:] if not p.startswith("--")]
        out.extend(PurePosixPath(a.rstrip("*").rstrip("/")) for a in args[:-1])
    return out


def is_copied(path: str, sources: list[PurePosixPath]) -> bool:
    """원본과 같거나 원본 디렉터리 안이면 True."""
    target = PurePosixPath(path)
    return any(target == s or s in target.parents for s in sources)


def _sources() -> list[PurePosixPath]:
    return copy_sources(DOCKERFILE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", RUNTIME_FILES)
def test_runtime_file_copied_into_image(path: str) -> None:
    """정상: 실행 중 읽는 리포 파일이 COPY 로 이미지에 들어간다 (develop 에서는 manifest 실패)."""
    assert (REPO_ROOT / path).is_file(), f"리포에 없음: {path}"
    assert is_copied(path, _sources()), f"Dockerfile COPY 에 없음: {path}"


def test_directory_copy_counts() -> None:
    """정상: `COPY src ./src` 같은 디렉터리 복사 안의 파일도 들어간 것으로 본다."""
    sources = copy_sources("COPY src ./src\nCOPY alembic.ini ./\n")
    assert is_copied("src/aml_ai/str/prompts/narrative_v2.md", sources)
    assert is_copied("alembic.ini", sources)
    assert not is_copied("srcx/a.py", sources)
    assert not is_copied("corpus/manifest.json", sources)
    assert is_copied("corpus/pdf", copy_sources("COPY corpus ./corpus\n"))  # 통째 복사도 잡힘


@pytest.mark.parametrize("path", FORBIDDEN)
def test_forbidden_path_not_copied(path: str) -> None:
    """경계: PDF 디렉터리는 직접이든 `corpus` 통째 복사로든 이미지에 안 들어간다."""
    assert not is_copied(path, _sources())


def test_copy_sources_exist_in_repo() -> None:
    """경계: COPY 원본은 리포에 실제로 있는 경로 (오타로 조용히 빠지지 않게)."""
    missing = [str(s) for s in _sources() if not list(REPO_ROOT.glob(str(s) + "*"))]
    assert missing == []
