"""mask_for_llm — LLM 에 가는 facts 만 바꾼다. 응답·DB 는 원본 (docs/str/04 마스킹 표)."""

from __future__ import annotations

from aml_ai.shared.schemas.str import Facts

ACCOUNT_TAIL = 4


def mask_account_key(key: str) -> str:
    """'010_8000EBD30' → '010_****BD30'. bank_id 는 남기고 계좌는 뒤 4자리만."""
    bank, _, acct = key.partition("_")
    if not acct:
        return "****" + key[-ACCOUNT_TAIL:]
    return f"{bank}_****{acct[-ACCOUNT_TAIL:]}"


def mask_for_llm(facts: Facts) -> Facts:
    """계좌번호 뒤 4자리만. 은행명·고객명·엔티티 ID 는 합성 데이터라 그대로 — 실데이터 전환 시 여기서 가명화."""
    return facts.model_copy(
        update={"subject_account_keys": [mask_account_key(k) for k in facts.subject_account_keys]}
    )
