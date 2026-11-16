"""SCRUM-228 — 하네스 커버리지가 v4 사전 표기를 인정 (docs/str/05 narrative_v4 "붙일 곳")."""

from __future__ import annotations

import pytest

from tests.str.rag_onoff_coverage import fact_coverage
from tests.str.v4_slot_support import FIXTURE_NAMES, assembled, load_fixture


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_v4_slots_cover_every_required_item_with_dictionary_labels(name: str) -> None:
    """코드 원문(`SALES_DEPOSIT`)이 아니라 사전 표기(`매출 대금 수납`)로 써도 누락으로 안 셈."""
    facts = load_fixture(name)
    assert fact_coverage(assembled(facts), facts)["missing"] == []
