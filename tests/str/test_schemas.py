"""facts·narrative 스키마 규칙 — docs/str/04·05."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aml_ai.shared.schemas.str import Facts, NarrativeOut
from tests.conftest import FIXTURES, load_json


def test_facts_fixture_valid() -> None:
    Facts.model_validate(load_json(FIXTURES / "facts_fan_in.json"))


def test_total_amount_must_be_two_decimal_string() -> None:
    d = load_json(FIXTURES / "facts_fan_in.json")
    d["total_amount"] = "320000000"
    with pytest.raises(ValidationError):
        Facts.model_validate(d)


def test_narrative_requires_each_section_once() -> None:
    d = load_json(FIXTURES / "narrative_ok.json")
    NarrativeOut.model_validate(d)
    d["narrative"][1]["section"] = "SUMMARY"
    with pytest.raises(ValidationError):
        NarrativeOut.model_validate(d)
