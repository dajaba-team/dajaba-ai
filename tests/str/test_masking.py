from __future__ import annotations

from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain.masking import mask_account_key, mask_for_llm
from tests.conftest import FIXTURES, load_json


def test_mask_account_key_keeps_bank_and_tail4() -> None:
    assert (
        mask_account_key("010_8000EBD30") == "010_****EBD30"[:4] + "****" + "BD30"
        or mask_account_key("010_8000EBD30") == "010_****BD30"
    )


def test_mask_for_llm_does_not_touch_original() -> None:
    facts = Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))
    masked = mask_for_llm(facts)
    assert masked.subject_account_keys == ["010_****BD30"]
    assert facts.subject_account_keys == ["010_8000EBD30"]
    assert masked.total_amount == facts.total_amount
