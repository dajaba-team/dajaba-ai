"""SCRUM-131 (2/n) 추가 검토 2차 — high 회귀, 본문·요약 둘 다 (docs/str/06 DATE_MATCH, 09).

① 괄호 없는 관측 범위 되돌림 — `거래 기간은 관측 결과 A부터 B까지` 는 거래 날짜.
② 은행·상대(C)는 추가 검토 3차에서 되돌려 테스트 없음(develop 동작).
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CodeCheck, CodeCheckName, SectionV2
from aml_ai.str.domain.verification import run_summary_code_checks
from tests.str.verification_support import date, facts_fan_in


def _lines(text: str, *, summary: bool) -> list[CodeCheck]:
    if summary:
        checks = run_summary_code_checks(facts_fan_in(), text.split("\n"), transaction_ids=[1])
    else:
        checks = date(facts_fan_in(), SectionV2.DATE, text)
    return [c for c in checks if c.check is CodeCheckName.DATE_MATCH]


@pytest.mark.parametrize("summary", [False, True])
def test_transaction_period_with_observation_word_is_transaction(summary: bool) -> None:
    """`거래 기간은 관측 결과 A부터 B까지` — 거래 날짜. 09-03 은 기간 밖 MISMATCH(관측 창 끝값과 안 맞춤)."""
    out = _lines("거래 기간은 관측 결과 2022-09-02부터 2022-09-03까지 확인됨", summary=summary)
    assert [(c.draft_value, c.match, (c.source_value or "").split(" ")[0]) for c in out] == [
        ("2022-09-02", True, "period"),
        ("2022-09-03", False, "period"),
    ]
