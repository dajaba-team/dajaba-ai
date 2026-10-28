"""mask_for_llm — LLM(생성기·평가자 공용)에 가는 facts 만 바꾼다. 응답·DB·코드 검증은 원본 (docs/str/04 마스킹 표)."""

from __future__ import annotations

from typing import Any

from aml_ai.shared.schemas.str import Facts, PathStatus

ACCOUNT_TAIL = 4
_DROP_KEY = "transaction_ids"
_PATH_KEEP = ("kind", "count", "max_hops", "max_accounts")


def mask_account_key(key: str) -> str:
    """'010_8000EBD30' → '010_****BD30'. bank_id 는 남기고 계좌는 뒤 4자리만."""
    bank, _, acct = key.partition("_")
    if not acct:
        return "****" + key[-ACCOUNT_TAIL:]
    return f"{bank}_****{acct[-ACCOUNT_TAIL:]}"


def _drop_ids(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _drop_ids(v) for k, v in node.items() if k != _DROP_KEY}
    if isinstance(node, list):
        return [_drop_ids(v) for v in node]
    return node


def mask_for_llm(facts: Facts) -> dict[str, Any]:
    """LLM 프롬프트용 JSON dict. Facts 모델이 아니다 — transaction_ids 가 빠져 스키마를 만족하지 않는다.

    - subject.account_key 뒤 4자리만, 은행명·고객명·엔티티 ID 는 그대로(합성 데이터)
    - 모든 transaction_ids 제거 — LLM 은 거래 ID 를 보지 않는다
    - indirect 통째로 제거 — 인용 키가 없는 사실
    - paths: VERIFIED 면 kind·count·max_hops·max_accounts 만, 아니면 통째로 제거
    """
    data = facts.model_dump(mode="json")
    data["subject"]["account_key"] = mask_account_key(facts.subject.account_key)
    data.pop("indirect", None)
    if facts.paths is not None and facts.paths.status is PathStatus.VERIFIED:
        data["paths"] = {k: data["paths"][k] for k in _PATH_KEEP}
    else:
        data.pop("paths", None)
    return _drop_ids(data)
