"""SCRUM-131 (2/n) 추가 검토 1차 — high 회귀, 본문·요약 둘 다 (docs/str/06 DATE_MATCH, 09).

① 관측 범위(2차에서 B 되돌림 — 괄호 없는 범위는 전부 거래 날짜) · ③ 개설 단어: 같은 절 날짜에만.
② 은행·상대(C)는 추가 검토 3차에서 되돌려 테스트 없음(develop 동작).
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CodeCheck, CodeCheckName, Facts, SectionV1
from aml_ai.str.domain.verification import run_summary_code_checks
from tests.str.verification_support import date, facts_fan_in


def _lines(facts: Facts, text: str, name: CodeCheckName, *, summary: bool) -> list[CodeCheck]:
    """본문은 SUMMARY 섹션 하나, 요약은 `\\n` 으로 나눈 줄들(요약 경로는 줄을 줄바꿈으로 이어 붙임)."""
    if summary:
        checks = run_summary_code_checks(facts, text.split("\n"), transaction_ids=[1])
    else:
        checks = date(facts, SectionV1.SUMMARY, text)
    return [c for c in checks if c.check is name]


def _view(checks: list[CodeCheck]) -> list[tuple[str | None, bool, str]]:
    return [(c.draft_value, c.match, (c.source_value or "").split(" ")[0]) for c in checks]


# ── ① 관측 범위 ──


@pytest.mark.parametrize("summary", [False, True])
def test_observation_value_said_first_then_range_is_transaction(summary: bool) -> None:
    """관측값(3.0)을 먼저 말한 뒤 범위 + `입금` → 거래 날짜. 09-03 은 기간 밖 MISMATCH 유지."""
    text = "모델 관측값은 3.0이며 2022-09-02부터 2022-09-03까지 입금 3건"
    out = _lines(facts_fan_in(), text, CodeCheckName.DATE_MATCH, summary=summary)
    assert _view(out) == [("2022-09-02", True, "period"), ("2022-09-03", False, "period")]


@pytest.mark.parametrize("summary", [False, True])
def test_transaction_word_after_range_is_transaction(summary: bool) -> None:
    """관측값을 아직 안 말했어도 범위 뒤 같은 절에 `입금` → 거래 날짜."""
    text = "모델 관측값은 2022-09-02부터 2022-09-03까지 입금된 금액 기준"
    out = _lines(facts_fan_in(), text, CodeCheckName.DATE_MATCH, summary=summary)
    assert [v[2] for v in _view(out)] == ["period", "period"]


@pytest.mark.parametrize("summary", [False, True])
def test_v1_unbracketed_observation_range_stays_mismatch(summary: bool) -> None:
    """v1 녹화 모양 — 괄호 없는 관측 범위는 거래 날짜(추가 검토 2차에서 B 되돌림), 둘 다 MISMATCH 고정."""
    text = "모델 관측값은 2022-09-02T00:00:00부터 2022-09-03T00:00:00까지의 24시간 기준 3.0"
    out = _lines(facts_fan_in(), text, CodeCheckName.DATE_MATCH, summary=summary)
    assert [(m, s) for _, m, s in _view(out)] == [(False, "period"), (False, "period")]


# ── ③ 개설 단어는 같은 절 ──


@pytest.mark.parametrize(
    ("text", "summary"),
    [
        ("2021-03-14 입금. 등록일은 확인되지 않음", False),
        ("2021-03-14 입금. 등록일은 확인되지 않음", True),
        ("2021-03-14 입금\n등록일은 확인되지 않음", True),
    ],
)
def test_onboard_word_does_not_cross_clause(text: str, summary: bool) -> None:
    """앞 절 입금 날짜가 뒤 절 `등록일` 에 붙지 않음 → 거래 날짜, 기간 밖 MISMATCH."""
    out = _lines(facts_fan_in(), text, CodeCheckName.DATE_MATCH, summary=summary)
    assert _view(out) == [("2021-03-14", False, "period")]


@pytest.mark.parametrize("summary", [False, True])
def test_correct_transaction_date_before_onboard_clause_matches(summary: bool) -> None:
    """날짜를 기간 안(2022-09-02)으로 바꾸면 match — 새 MISMATCH 없음."""
    text = "2022-09-02 입금\n등록일은 확인되지 않음" if summary else "2022-09-02 입금. 등록일은 확인되지 않음"
    out = _lines(facts_fan_in(), text, CodeCheckName.DATE_MATCH, summary=summary)
    assert _view(out) == [("2022-09-02", True, "period")]


@pytest.mark.parametrize("summary", [False, True])
def test_v1_registered_date_still_onboard(summary: bool) -> None:
    out = _lines(facts_fan_in(), "고객 등록일은 2021-03-14이며", CodeCheckName.DATE_MATCH, summary=summary)
    assert _view(out) == [("2021-03-14", True, "onboarded_at")]
