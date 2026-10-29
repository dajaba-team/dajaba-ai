"""기동 시 prompts/*.md 의 sha256 을 ai.prompt_versions 에 색인 + 동결 강제 (docs/str/05·shared/04).

동결 = `FROZEN_PROMPTS` dict 의 (name→hash). 파일 해시가 다르면 **기동 실패**(DB 없이도 걸림).
DB 색인은 best-effort(실패해도 기동은 안 막음). frozen_at 은 FROZEN_PROMPTS 에 있으면 색인 때 채움.
"""

from __future__ import annotations

import logging

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from aml_ai.shared.config import Settings
from aml_ai.shared.db import get_engine
from aml_ai.shared.versioning import file_sha256
from aml_ai.str.domain import constants as _const
from aml_ai.str.infrastructure.narrative_generator import PROMPTS_DIR
from aml_ai.str.infrastructure.orm import PromptVersion

log = logging.getLogger(__name__)


class FrozenPromptMismatch(RuntimeError):
    """동결된 프롬프트의 파일 해시가 FROZEN_PROMPTS 값과 다름. 기동이 막힌다."""


def check_frozen_prompts() -> None:
    """FROZEN_PROMPTS 에 적힌 모든 버전의 파일 해시를 대조. 다르면 FrozenPromptMismatch."""
    for stem, expected in _const.FROZEN_PROMPTS.items():
        path = PROMPTS_DIR / f"{stem}.md"
        if not path.exists():
            raise FrozenPromptMismatch(f"frozen prompt file missing: {stem}.md")
        actual = file_sha256(path)
        if actual != expected:
            raise FrozenPromptMismatch(
                f"frozen prompt hash mismatch for {stem}: expected={expected[:12]} actual={actual[:12]}"
            )


def index_prompt_files(settings: Settings) -> None:
    """DB 에 색인(선택). FROZEN_PROMPTS 는 import 시점에 이미 검사됨 — 기동 코드가 먼저 부른다."""
    try:
        with Session(get_engine()) as s:
            for path in sorted(PROMPTS_DIR.glob("*_v*.md")):
                name, _, version = path.stem.rpartition("_")
                stmt = (
                    insert(PromptVersion)
                    .values(
                        prompt_name=name,
                        version=version,
                        file_hash=file_sha256(path),
                    )
                    .on_conflict_do_nothing()
                )
                s.execute(stmt)
            s.commit()
    except Exception as exc:  # noqa: BLE001 — DB 색인 실패가 기동을 막지 않는다. 동결은 위에서 걸림
        log.warning("prompt_index_skipped", extra={"reason": type(exc).__name__})
