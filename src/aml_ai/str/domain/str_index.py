"""승인 STR 색인 — 청크 나누기·본문 해시·짧음 판정 (SCRUM-310·361, docs/str/10 "승인 STR 색인"). 순수.

섹션(≤5000자)을 청크(≤1200자, 코드 포인트)로 나눔 — 문장 끝에서 앞부터 채움, 1200 넘는 한 문장만 자르고 꼬리는
다음 문장과 이어 채움, 공백만인 청크는 만들지 않음 — 공백만 조각은 앞 청크 남은 자리 → 다음 문장 앞에 붙이고
둘 다 꽉 찼을 때만 버림(SCRUM-361, 추가 검토 1 M1). 공백만인 섹션은 뺌.
상한: 단락마다 ⌊글자 수 ÷ 600⌋ + 1 — 이웃 두 청크 길이 합이 늘 1200 을 넘으므로(백엔드 응답 확인과 같은 식).
`request_hash` = sha256(정규 JSON — 문서번호·초안 id·승인 시각·유형(정렬)·섹션 순서대로 이름과 글): 같은 문서번호 재요청 비교.
"""

from __future__ import annotations

import hashlib
import json
import re

from aml_ai.shared.schemas.str import StrIndexRequest
from aml_ai.str.domain.constants_rag_query import STR_INDEX_CHUNK_MAX

_SPACE = re.compile(r"\s+")
# 문장 = 마침표·물음표·느낌표 + 공백, 또는 줄바꿈 + 그 뒤 공백까지(끝 공백은 그 문장에 붙음) — 마지막 조각은 끝까지
_SENTENCE = re.compile(r".*?(?:[.?!]\s+|\n\s*|$)", re.S)


def section_texts(req: StrIndexRequest) -> list[str]:
    """나누기 전 섹션 글 — 요청 순서, 공백만인 섹션 제외. 계좌 원문·짧음 판정은 이것으로(나누기 전)."""
    return [s.text for s in req.sections if s.text.strip()]


def chunks(req: StrIndexRequest) -> list[tuple[str, int, str]]:
    """(섹션 이름, 순번(1부터), 청크 글) — 요청 순서, 공백만인 섹션 제외."""
    return [
        (s.section, seq, piece)
        for s in req.sections
        if s.text.strip()
        for seq, piece in enumerate(split_text(s.text), start=1)
    ]


def chunk_id(report_no: str, section: str, seq: int) -> str:
    return f"{report_no}:{section}:{seq}"


def split_text(text: str, limit: int = STR_INDEX_CHUNK_MAX) -> list[str]:
    """글 → 청크(각 1~limit 자). 이어 붙이면 원문 그대로 — 앞뒤가 꽉 차 못 붙인 공백만 빠짐(순서 그대로, 겹치지 않음)."""
    acc = _Chunks(limit)
    cur = ""
    for sentence in (m.group(0) for m in _SENTENCE.finditer(text) if m.group(0)):
        while sentence:
            if len(cur) + len(sentence) <= limit:
                cur, sentence = cur + sentence, ""
                continue
            left = acc.close(cur)  # 지금 청크를 닫음 — 공백만이면 앞 청크에 붙이고 남은 공백
            cur = ""
            if (
                len(sentence) <= limit
            ):  # 다음 문장이 남은 자리에 안 들어감 → 남은 공백은 다음 문장 앞에 자리만큼
                room = limit - len(sentence)
                sentence = (left[-room:] if room else "") + sentence
            else:  # 1200 넘는 한 문장 — 그 문장만 자름, 꼬리는 다음 문장과 이어 채움
                sentence = left + sentence
                rest = acc.close(sentence[:limit])  # 잘린 조각이 공백뿐이면 못 붙인 몫은 보관(검토 2 M)
                acc.carry += rest
                sentence = sentence[limit:]
    acc.close(cur)
    return acc.out


def chunk_bound(text: str) -> int:
    """청크 수 상한 — ⌊글자 수(코드 포인트, 원문 그대로) ÷ 600⌋ + 1 (공백만이면 0). 백엔드 응답 확인과 같은 식."""
    return len(text) // (STR_INDEX_CHUNK_MAX // 2) + 1 if text.strip() else 0


class _Chunks:
    """닫은 청크 + 붙일 곳을 아직 못 찾은 공백(`carry` — 다음 청크 앞에 자리만큼 붙임)."""

    def __init__(self, limit: int) -> None:
        self.out: list[str] = []
        self.carry = ""
        self.limit = limit

    def close(self, piece: str) -> str:
        """청크를 닫음. 공백만이면 청크를 만들지 않고 앞 청크 남은 자리에 붙임 → 못 붙인 공백을 돌려줌."""
        if piece.strip():
            room = self.limit - len(piece)
            self.out.append((self.carry[-room:] if room else "") + piece)
            self.carry = ""
            return ""
        room = (
            self.limit - len(self.out[-1]) if self.out and not self.carry else 0
        )  # 보관 공백이 있으면 앞은 꽉 참
        if room:
            self.out[-1] += piece[:room]
        return piece[room:]


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
