"""승인 STR 색인 — 청크·본문 해시·짧음 판정 (SCRUM-310, docs/str/10 "승인 STR 색인"). 순수.

섹션 하나 = 청크 하나(섹션 ≤ 1200자라 나누지 않음) · 공백만인 섹션은 뺌.
`request_hash` = sha256(정규 JSON — 문서번호·초안 id·승인 시각·유형(정렬)·섹션 순서대로 이름과 글): 같은 문서번호 재요청 비교.
"""

from __future__ import annotations

import hashlib
import json
import re

from aml_ai.shared.schemas.str import StrIndexRequest

_SPACE = re.compile(r"\s+")


def chunks(req: StrIndexRequest) -> list[tuple[str, str]]:
    """(섹션 이름, 글) — 요청 순서, 공백만인 섹션 제외."""
    return [(s.section, s.text) for s in req.sections if s.text.strip()]


def chunk_id(report_no: str, section: str) -> str:
    return f"{report_no}:{section}"


def content_chars(req: StrIndexRequest) -> int:
    return sum(len(_SPACE.sub("", s.text)) for s in req.sections)


def request_hash(req: StrIndexRequest) -> str:
    body = req.model_dump(mode="json")
    canonical = {
        "report_no": body["report_no"],
        "draft_id": body["draft_id"],
        "approved_at": body["approved_at"],
        "typologies": sorted(body["typologies"]),
        "sections": [[s["section"], s["text"]] for s in body["sections"]],
    }
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def case_seed(facts: dict) -> tuple[str | None, list[int]]:
    """초안 facts(저장분 JSON) → (대상 계좌 키, 거래 ID 전부) — 상대 계좌는 거래 ID 로 원천 표에서 읽음(facts 엔 키가 없음)."""
    ids: set[int] = set()

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "transaction_ids" and isinstance(v, list):
                    ids.update(i for i in v if isinstance(i, int))
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(facts)
    subject = (facts.get("subject") or {}).get("account_key")
    return (subject if isinstance(subject, str) else None), sorted(ids)
