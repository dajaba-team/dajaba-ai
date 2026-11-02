"""코드 검증 단위 — docs/str/06 유형별 대조.

EVIDENCE_IN_SCOPE 기존 (SCRUM-12·13). AMOUNT·ACCOUNT 는 각자 파일(SCRUM-58).
`date_match`·`count_match` 는 59·60. 공용 helpers 는 `verification_support.py`.
"""

from __future__ import annotations

from aml_ai.str.domain import verification
from tests.str.verification_support import narrative_ok


def test_evidence_in_scope_passes_for_fixture() -> None:
    checks = verification.evidence_in_scope(narrative_ok(), [1, 2, 3])
    assert all(c.match for c in checks)


def test_evidence_out_of_scope_fails_section() -> None:  # 오류 주입 5
    n = narrative_ok()
    n[2].evidence_ids.append(999)
    checks = verification.evidence_in_scope(n, [1, 2, 3])
    assert any(not c.match and c.section == n[2].section for c in checks)


def test_all_empty_evidence_fails() -> None:  # 오류 주입 6
    n = [s.model_copy(update={"evidence_ids": []}) for s in narrative_ok()]
    checks = verification.evidence_in_scope(n, [1, 2, 3])
    assert any(not c.match and c.section is None for c in checks)
