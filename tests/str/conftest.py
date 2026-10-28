"""tests/str 공용 픽스처."""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import Facts
from tests.str.facts_support import CASES, build


@pytest.fixture(scope="module")
def mixed() -> Facts:
    """facts_cases.json "mixed" — inbound 2통화·outbound·internal·indirect·self-transfer 가 다 있는 경보."""
    return build(CASES["mixed"])
