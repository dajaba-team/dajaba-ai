"""기동 시 prompts/*.md 의 sha256 을 ai.prompt_versions 에 색인. 파일이 정본, DB 는 색인 (docs/shared/04)."""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.db import get_engine
from aml_ai.shared.versioning import file_sha256
from aml_ai.str.infrastructure.narrative_generator import PROMPTS_DIR
from aml_ai.str.infrastructure.orm import PromptVersion

log = logging.getLogger(__name__)


def index_prompt_files(settings: Settings) -> None:
    try:
        with Session(get_engine()) as s:
            for path in sorted(PROMPTS_DIR.glob("*_v*.md")):
                name, _, version = path.stem.rpartition("_")
                stmt = (
                    insert(PromptVersion)
                    .values(prompt_name=name, version=version, file_hash=file_sha256(path))
                    .on_conflict_do_nothing()
                )
                s.execute(stmt)
            s.commit()
    except Exception as exc:  # noqa: BLE001 — 색인 실패가 기동을 막지 않는다
        log.warning("prompt_index_skipped", extra={"reason": type(exc).__name__})
