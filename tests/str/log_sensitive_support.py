"""SCRUM-272 — 민감 값 미포함 테스트 재료 (docs/shared/04 "남기지 않는 것").

픽스처(ops_seed.sql · contracts/examples) 값에서 "로그에 나오면 안 되는 문자열"을 모은다.
"""

from __future__ import annotations

import json
import re

from aml_ai.shared.schemas.str import DraftResponse
from tests.log_support import parse_lines

ACCOUNT_KEYS = ("10_8000EBD30", "020_C0000001", "020_C0000002", "020_C0000003")
MASKED_KEYS = ("10_****BD30", "020_****0001", "020_****0002", "020_****0003")
SUBJECT_TAIL = "BD30"  # 대상 계좌 끝 4자리 묶음(상대 "0001" 등은 hex request_id 와 겹칠 수 있어 가린 꼴로만)
# ops_seed 거래 3건 · 합계 · rule_facts.total_amount_received — 쉼표 있/없, 소수 자리 있/없
AMOUNTS = ("12500", "12,500", "14000", "14,000", "16250.5", "16,250.5", "42750.5", "42,750.5")
NOTES = "입금 직후 두 계좌로 분산. 매출 규모 대비 비정상."
NOTE_SENTENCES = ("입금 직후 두 계좌로 분산", "매출 규모 대비 비정상")
TEXT_PROBE_LEN = 20  # 본문은 전문 + 앞 20자
# 본문·메모는 한국어, 로그는 영문 사건 이름·코드뿐 — Pydantic 오류는 본문을 앞뒤 몇 글자만 남기고 잘라
# ("'입금 직후 ...30 12,500'") 전문·앞 20자 대조를 빠져나감. 한글 한 글자라도 있으면 본문 조각으로 본다.
HANGUL = re.compile(r"[\uac00-\ud7a3]+")


def fixed_values() -> list[str]:
    return [*ACCOUNT_KEYS, *MASKED_KEYS, SUBJECT_TAIL, *AMOUNTS, NOTES, *NOTE_SENTENCES]


def narrative_values(*drafts: DraftResponse) -> list[str]:
    values: list[str] = []
    for draft in drafts:
        for sec in draft.narrative:
            values += [sec.text, sec.text[:TEXT_PROBE_LEN]]
    return values


def leaked(out: str, values: list[str]) -> list[str]:
    """원문 + JSON 을 푼 글자 모두에서 찾는다 — 포매터가 한글을 `\\uXXXX` 로 적으면 원문 대조로는 안 보임."""
    text = out + "\n" + "\n".join(json.dumps(line, ensure_ascii=False) for line in parse_lines(out))
    return sorted({v for v in values if v and v in text} | set(HANGUL.findall(text)))


def with_notes(body: dict) -> dict:
    return {**body, "investigator_notes": NOTES}
