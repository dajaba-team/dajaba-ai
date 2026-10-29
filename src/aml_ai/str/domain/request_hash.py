"""draft 요청 바디 canonical JSON sha256 — docs/shared/03 "같은 draft_id 재요청".

SCRUM-14. 수정본 narrative 해시(`shared/hashing.narrative_sha256`, SCRUM-16)와 다른 함수 —
파일을 나눠 PR 충돌을 피한다. 규약 JSON 모양이 아니라 순수 계산이라 domain 쪽.
"""

from __future__ import annotations

import hashlib
import json

from aml_ai.shared.schemas.str import DraftRequest


def request_hash(req: DraftRequest) -> str:
    """바디 canonical JSON(sort_keys · no whitespace · ensure_ascii=False)의 sha256 hex. draft_id 포함."""
    body = json.dumps(req.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
