"""SCRUM-60 조정 — run_code_checks 가 끝까지 돌고 narrative_ok 가 전부 match (docs/str/06).

- `test_run_code_checks_has_count_and_date` — DATE_MATCH·COUNT_MATCH 결과 **둘 다** 있고 전부 match
- `test_count_match_narrative_ok_all_match` — count_match 가 narrative_ok 를 전부 통과(61 녹화 PASSED 전제)
- `test_narrative_ok_is_v1_six_sections` — fixture 전제 유지
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CodeCheckName, SectionV1
from aml_ai.str.domain import verification
from tests.str.verify_service_support import facts_fan_in, narrative_ok


def test_run_code_checks_has_count_and_date() -> None:
    """DATE_MATCH·COUNT_MATCH 둘 다 결과 있고 narrative_ok 섹션들에서 전부 match."""
    facts = facts_fan_in()
    narrative = narrative_ok()
    checks = verification.run_code_checks(facts, narrative, [1, 2, 3])
    kinds = {c.check for c in checks}
    assert CodeCheckName.DATE_MATCH in kinds
    assert CodeCheckName.COUNT_MATCH in kinds  # SCRUM-60
    assert CodeCheckName.EVIDENCE_IN_SCOPE in kinds  # v1 집합이라 OPINION_PRESENT 는 안 돎
    bad = [c for c in checks if not c.match]
    assert not bad, [(c.check, c.section, c.draft_value, c.source_value, c.reason) for c in bad]


def test_count_match_narrative_ok_all_match() -> None:
    """SCRUM-60 — count_match 가 narrative_ok 전 섹션을 통과(61 verify 녹화 PASSED 전제)."""
    facts = facts_fan_in()
    narrative = narrative_ok()
    checks = verification.count_match(facts, narrative)
    assert all(c.match for c in checks), [
        (c.section, c.draft_value, c.source_value, c.reason) for c in checks if not c.match
    ]


def test_narrative_ok_is_v1_six_sections() -> None:
    """narrative_ok 는 v1 6섹션 — 다른 테스트의 전제가 흔들리지 않는지 한 번 확인."""
    narrative = narrative_ok()
    assert [s.section for s in narrative] == list(SectionV1)
