"""SCRUM-91 — run_code_checks 가 59·60 전 상태에서도 끝까지 돈다 (docs/str/06).

- `test_run_code_checks_no_date_count_results` — DATE_MATCH·COUNT_MATCH 결과 0개, 예외 없음
- `test_date_count_return_empty_lists` — 두 함수 직접 호출 → 빈 목록
- `test_narrative_ok_is_v1_six_sections` — fixture 전제 유지(섹션 집합 안 흔들림)

develop 에서는 `date_match` NotImplementedError 로 run_code_checks 자체가 500 — 수정 뒤에만 통과.
"""

from __future__ import annotations

from aml_ai.shared.schemas.str import CodeCheckName, SectionV1
from aml_ai.str.domain import verification
from tests.str.verify_service_support import facts_fan_in, narrative_ok


def test_run_code_checks_no_date_count_results() -> None:
    facts = facts_fan_in()
    narrative = narrative_ok()
    checks = verification.run_code_checks(facts, narrative, [1, 2, 3])
    kinds = {c.check for c in checks}
    assert CodeCheckName.DATE_MATCH not in kinds
    assert CodeCheckName.COUNT_MATCH not in kinds
    # v1 집합이라 OPINION_PRESENT 는 안 돌고, EVIDENCE_IN_SCOPE 는 돈다
    assert CodeCheckName.EVIDENCE_IN_SCOPE in kinds


def test_date_count_return_empty_lists() -> None:
    """SCRUM-91 — 두 함수가 빈 목록(docstring '59·60 전까지 결과 없음')."""
    facts = facts_fan_in()
    narrative = narrative_ok()
    assert verification.date_match(facts, narrative) == []
    assert verification.count_match(facts, narrative) == []


def test_narrative_ok_is_v1_six_sections() -> None:
    """narrative_ok 는 v1 6섹션 — 다른 테스트의 전제가 흔들리지 않는지 한 번 확인."""
    narrative = narrative_ok()
    assert [s.section for s in narrative] == list(SectionV1)
