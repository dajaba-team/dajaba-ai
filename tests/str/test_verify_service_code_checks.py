"""SCRUM-91 → SCRUM-59 조정 — run_code_checks 가 끝까지 돌고 narrative_ok 가 전부 match (docs/str/06).

- `test_run_code_checks_has_date_no_count` — DATE_MATCH 결과 **있고** 전부 match, COUNT_MATCH 는 60 전까지 없음
- `test_count_match_returns_empty_list` — count 만 빈 목록(date 는 narrative_ok 로 전부 match)
- `test_narrative_ok_is_v1_six_sections` — fixture 전제 유지(섹션 집합 안 흔들림)

develop 7f0cbfa 에서 SCRUM-91 머지 뒤 상태. SCRUM-59 로 date_match 활성 → 두 테스트 수정.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CodeCheckName, SectionV1
from aml_ai.str.domain import verification
from tests.str.verify_service_support import facts_fan_in, narrative_ok


def test_run_code_checks_has_date_no_count() -> None:
    """DATE_MATCH 결과가 있고 narrative_ok 섹션들에서 전부 match. COUNT_MATCH 는 아직 없음(60)."""
    facts = facts_fan_in()
    narrative = narrative_ok()
    checks = verification.run_code_checks(facts, narrative, [1, 2, 3])
    kinds = {c.check for c in checks}
    assert CodeCheckName.DATE_MATCH in kinds
    assert CodeCheckName.COUNT_MATCH not in kinds
    # v1 집합이라 OPINION_PRESENT 는 안 돌고, EVIDENCE_IN_SCOPE 는 돈다
    assert CodeCheckName.EVIDENCE_IN_SCOPE in kinds
    date_checks = [c for c in checks if c.check is CodeCheckName.DATE_MATCH]
    assert date_checks, "DATE_MATCH 결과가 하나도 없으면 narrative_ok 에 날짜 표현이 모두 사라진 것"
    assert all(c.match for c in date_checks), [
        (c.section, c.draft_value, c.source_value, c.reason) for c in date_checks if not c.match
    ]


def test_count_match_returns_empty_list() -> None:
    """SCRUM-91 → SCRUM-59 — count_match 만 빈 목록. date_match 는 narrative_ok 로 전부 match."""
    facts = facts_fan_in()
    narrative = narrative_ok()
    assert verification.count_match(facts, narrative) == []
    date_checks = verification.date_match(facts, narrative)
    assert date_checks and all(c.match for c in date_checks)


def test_narrative_ok_is_v1_six_sections() -> None:
    """narrative_ok 는 v1 6섹션 — 다른 테스트의 전제가 흔들리지 않는지 한 번 확인."""
    narrative = narrative_ok()
    assert [s.section for s in narrative] == list(SectionV1)
