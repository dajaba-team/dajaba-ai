"""코드 검증 단위 — docs/str/06 유형별 대조.

EVIDENCE_IN_SCOPE (SCRUM-12·13 → SCRUM-60 cites 기준으로 보강). AMOUNT·ACCOUNT·DATE·COUNT 는 각자 파일.
"""

from __future__ import annotations

from aml_ai.str.domain import verification
from aml_ai.str.domain.fact_keys import fact_keys
from tests.str.verification_support import facts_fan_in, narrative_ok


def _facts_and_keys():
    facts = facts_fan_in()
    return facts, fact_keys(facts)


def test_evidence_in_scope_passes_for_fixture() -> None:
    _, keys = _facts_and_keys()
    checks = verification.evidence_in_scope(narrative_ok(), [1, 2, 3], keys)
    assert all(c.match for c in checks)


def test_evidence_out_of_scope_fails_section_evidence_ids() -> None:
    """오류 주입 5(evidence_ids 밖) — SCRUM-57 저장 경로 호환 회귀."""
    _, keys = _facts_and_keys()
    n = narrative_ok()
    n[2] = n[2].model_copy(update={"evidence_ids": [*n[2].evidence_ids, 999]})
    checks = verification.evidence_in_scope(n, [1, 2, 3], keys)
    assert any(not c.match and c.section == n[2].section for c in checks)


def test_evidence_out_of_scope_fails_section_cites() -> None:
    """★ SCRUM-60 — cites 에 fact_keys 밖 키가 있으면 OUT_OF_SCOPE."""
    _, keys = _facts_and_keys()
    n = narrative_ok()
    n[1] = n[1].model_copy(update={"cites": [*n[1].cites, "no_such_fact_key"]})
    checks = verification.evidence_in_scope(n, [1, 2, 3], keys)
    bad = [c for c in checks if not c.match and c.section == n[1].section]
    assert bad, "cites 에 fact_keys 밖 키가 있으면 OUT_OF_SCOPE 가 나와야 함"


def test_all_empty_cites_fails_missing() -> None:
    """오류 주입 6 — 모든 섹션 cites 가 전부 빔 → MISSING 1줄."""
    _, keys = _facts_and_keys()
    n = [s.model_copy(update={"cites": [], "evidence_ids": []}) for s in narrative_ok()]
    checks = verification.evidence_in_scope(n, [1, 2, 3], keys)
    assert any(not c.match and c.section is None for c in checks)


def test_narrative_ok_cites_all_in_fact_keys() -> None:
    """narrative_ok 의 모든 섹션 cites 가 fact_keys 안에 — 61 verify 녹화 통합 전제."""
    _, keys = _facts_and_keys()
    for s in narrative_ok():
        bad = [k for k in s.cites if k not in keys]
        assert not bad, f"{s.section}: fact_keys 밖 cites = {bad}"
