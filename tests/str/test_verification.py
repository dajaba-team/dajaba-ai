"""코드 검증 — EVIDENCE_IN_SCOPE 는 뼈대에서 구현됨. 나머지 셋은 W3 (NotImplemented → skip)."""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import NarrativeSection
from aml_ai.str.domain import verification
from tests.conftest import FIXTURES, load_json


def _narrative() -> list[NarrativeSection]:
    return [
        NarrativeSection.model_validate(s) for s in load_json(FIXTURES / "narrative_ok.json")["narrative"]
    ]


def test_evidence_in_scope_passes_for_fixture() -> None:
    checks = verification.evidence_in_scope(_narrative(), [1, 2, 3])
    assert all(c.match for c in checks)


def test_evidence_out_of_scope_fails_section() -> None:  # 오류 주입 5
    n = _narrative()
    n[2].evidence_ids.append(999)
    checks = verification.evidence_in_scope(n, [1, 2, 3])
    assert any(not c.match and c.section == n[2].section for c in checks)


def test_all_empty_evidence_fails() -> None:  # 오류 주입 6
    n = [s.model_copy(update={"evidence_ids": []}) for s in _narrative()]
    checks = verification.evidence_in_scope(n, [1, 2, 3])
    assert any(not c.match and c.section is None for c in checks)


@pytest.mark.skip(reason="W3 — docs/str/06 AMOUNT_MATCH·DATE_MATCH·COUNTERPARTY_COUNT 구현 뒤 오류 주입 1~4")
def test_other_code_checks() -> None: ...
