"""마스킹 — docs/str/04 마스킹 표. LLM 에 가는 것만 바뀌고 원본 facts 는 그대로."""

from __future__ import annotations

from aml_ai.shared.schemas.str import Facts, PathFacts, PathKind, PathStatus
from aml_ai.str.domain.masking import mask_account_key, mask_for_llm
from tests.conftest import FIXTURES, load_json


def _facts() -> Facts:
    return Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))


def _has_key(node: object, key: str) -> bool:
    if isinstance(node, dict):
        return key in node or any(_has_key(v, key) for v in node.values())
    if isinstance(node, list):
        return any(_has_key(v, key) for v in node)
    return False


def test_mask_account_key_keeps_bank_and_tail4() -> None:
    assert mask_account_key("010_8000EBD30") == "010_****BD30"


def test_mask_account_key_without_bank() -> None:  # 경계: '_' 없는 키
    assert mask_account_key("8000EBD30") == "****BD30"


def test_mask_for_llm_does_not_touch_original() -> None:
    facts = _facts()
    masked = mask_for_llm(facts)
    assert masked["subject"]["account_key"] == "010_****BD30"
    assert facts.subject.account_key == "010_8000EBD30"
    assert masked["inbound"]["by_currency"][0]["total"] == facts.inbound.by_currency[0].total


def test_mask_for_llm_drops_all_transaction_ids_and_indirect() -> None:
    masked = mask_for_llm(_facts())
    assert not _has_key(masked, "transaction_ids")
    assert "indirect" not in masked


def test_mask_for_llm_keeps_only_verified_paths() -> None:
    verified = PathFacts(
        kind=PathKind.CYCLE,
        status=PathStatus.VERIFIED,
        count=2,
        max_hops=3,
        max_accounts=3,
        transaction_ids=[1, 2, 3],
    )
    m = mask_for_llm(_facts().model_copy(update={"paths": verified}))
    assert m["paths"] == {"kind": "CYCLE", "count": 2, "max_hops": 3, "max_accounts": 3}

    unverified = verified.model_copy(update={"status": PathStatus.UNVERIFIED})
    assert "paths" not in mask_for_llm(_facts().model_copy(update={"paths": unverified}))
