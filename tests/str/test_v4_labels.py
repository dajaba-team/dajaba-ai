"""SCRUM-228 — 표기 사전 `contracts/display_labels_v1.json` (docs/str/05 narrative_v4 "표기 사전")."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aml_ai.shared.schemas.common import Typology
from aml_ai.shared.schemas.str.facts_enums import EntityType
from aml_ai.str.domain import masking
from aml_ai.str.domain.constants import PAYMENT_FORMAT_ALIASES
from aml_ai.str.domain.constants_currency import CURRENCY_ALIASES
from aml_ai.str.domain.constants_v4 import LABEL_BANNED_WORDS, LABEL_FIELDS
from aml_ai.str.domain.display_labels_check import missing_labels, used_codes
from aml_ai.str.infrastructure.display_labels import LABELS_PATH, load_display_labels
from tests.str.v4_slot_support import facts_sources

LABELS = load_display_labels()


def test_labels_have_every_field_and_no_empty_label() -> None:
    assert set(LABELS) == set(LABEL_FIELDS)
    for field, table in LABELS.items():
        if field == "observation_unit":
            continue  # 단위 없음("")이 정상 값
        assert all(v.strip() for v in table.values()), field


def test_labels_avoid_checker_kind_words() -> None:
    for field, table in LABELS.items():
        for code, label in table.items():
            assert not any(w in label for w in LABEL_BANNED_WORDS), (field, code, label)


def test_enum_fields_cover_every_enum_value() -> None:
    assert set(LABELS["entity_type"]) == {e.value for e in EntityType}
    assert set(LABELS["typology"]) == {t.value for t in Typology}


def test_currency_labels_are_amount_match_aliases() -> None:
    assert set(LABELS["currency"]) == set(CURRENCY_ALIASES)
    for code, label in LABELS["currency"].items():
        assert label in CURRENCY_ALIASES[code], code


def test_payment_labels_are_count_aliases_except_bitcoin() -> None:
    """COUNT ⑥ 이 읽는 표기만. alias 없는 Bitcoin 은 슬롯이 건수 없이 이름만 씀(09 2026-11-17)."""
    for fmt, label in LABELS["payment_format"].items():
        if fmt == "Bitcoin":
            assert fmt not in PAYMENT_FORMAT_ALIASES
            continue
        assert label in PAYMENT_FORMAT_ALIASES[fmt], fmt


def test_count_unit_label_is_count_unit() -> None:
    """관측 count 는 `개`(COUNT 관측값), 금액·비율은 단위 없음(통화 이름 붙이면 AMOUNT 가 합계와 대조)."""
    assert LABELS["observation_unit"] == {"count": "개", "ratio": "", "amount": ""}


@pytest.mark.parametrize("source", [s for s, _ in facts_sources()])
def test_fixture_and_fewshot_codes_all_in_dictionary(source: str) -> None:
    facts = dict(facts_sources())[source]
    assert missing_labels(masking.mask_for_llm(facts), LABELS) == []


def test_missing_label_reports_field_and_code() -> None:
    _, facts = facts_sources()[0]
    masked = masking.mask_for_llm(facts)
    masked["customer"]["industry"] = "SPACE_MINING"
    masked["payment_format_counts"].append({"format": "Teleport", "count": 1})
    assert missing_labels(masked, LABELS) == [("industry", "SPACE_MINING"), ("payment_format", "Teleport")]


def test_null_codes_skip_dictionary() -> None:
    _, facts = facts_sources()[0]
    masked = masking.mask_for_llm(facts)
    masked["customer"] = None
    masked["typology"] = None
    fields = {f for f, _ in used_codes(masked)}
    assert "industry" not in fields and "typology" not in fields


def test_loader_rejects_wrong_version(tmp_path: Path) -> None:
    data = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    data["version"] = "display-labels-v0"
    p = tmp_path / "labels.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        load_display_labels.__wrapped__(p)
