"""SCRUM-310 승인 STR 색인 — 기동 때 고정한 `retrieval_version` (추가 검토 2 M6, docs/str/10 "승인 STR 색인").

참고 사례 검색(309)과 같은 값(`base_retrieval_version`, 모델@manifest 8자)을 lifespan 에서 한 번 읽음 — 요청마다 manifest 를
읽지 않음(기동 뒤 파일이 바뀌거나 읽기가 실패해도 응답·새 행 버전은 기동 때 값).
"""

from __future__ import annotations

from aml_ai.shared.config import Settings
from aml_ai.shared.versioning import base_retrieval_version

_version: str | None = None


def start(settings: Settings) -> None:
    global _version  # noqa: PLW0603 — 프로세스 하나에 한 번(기동)
    _version = base_retrieval_version(settings, strict=True)


def version() -> str | None:
    return _version


def stop() -> None:
    global _version  # noqa: PLW0603
    _version = None
