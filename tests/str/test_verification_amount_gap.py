"""AMOUNT_MATCH 안전망 — 관측 문장 안 금액 (SCRUM-131 1/n 추가 검토 2·3차). 정본 docs/str/06 안전망 ②.

관측 단어로 숫자를 빼는 규칙은 두지 않는다 — 관측 제외가 두 번 실제 금액까지 빼서 원래 누락
(틀린 금액인데 AMOUNT_MATCH 0줄)을 다시 열었음. 1차 오탐은 `기준` 낱말·줄바꿈 경계가 막는다.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CheckReason, CodeCheckName, Facts, SectionV1
from aml_ai.str.domain.verification import run_summary_code_checks
from tests.conftest import FIXTURES, load_json
from tests.str.verification_support import amount

AFTER_OBSERVATION = "모델 관측값은 31이며 입금 합계는 945831.63 일본국 엔(JPY)임"


def _facts(code: str, total: str) -> Facts:
    data = load_json(FIXTURES / "facts_fan_in.json")
    base = data["inbound"]["by_currency"][0]
    data["inbound"]["by_currency"] = [{**base, "currency": code, "total": total}]
    data["amount_range"] = [{"currency": code, "min": total, "max": total}]
    return Facts.model_validate(data)


JPY = _facts("JPY", "954831.63")
USD = _facts("USD", "42750.50")


def _amount_lines(facts: Facts, text: str, *, summary: bool) -> list:
    if summary:
        checks = run_summary_code_checks(facts, text.split("\n"), transaction_ids=[1])
        return [c for c in checks if c.check is CodeCheckName.AMOUNT_MATCH]
    return amount(facts, SectionV1.SUMMARY, text)


@pytest.mark.parametrize("summary", [False, True])
@pytest.mark.parametrize(
    "text",
    [
        AFTER_OBSERVATION,
        "모델 관측값 기준 입금 합계 945831.63 일본국 엔",
        "모델 관측값 기준 입금 합계 945831.63 일본국 엔(JPY)임",
    ],
)
def test_amount_in_observation_sentence_still_checked(text: str, summary: bool) -> None:
    lines = _amount_lines(JPY, text, summary=summary)
    assert [(c.draft_value, c.reason) for c in lines] == [("945831.63 일본국 (JPY)", CheckReason.UNPARSED)]


@pytest.mark.parametrize("summary", [False, True])
@pytest.mark.parametrize(
    "text", ["모델 관측값 31.0 기준 미국 달러로 입금", "모델 관측값은 31.0\n입금 통화는 미국 달러임"]
)
def test_first_round_false_positives_stay_blocked(text: str, summary: bool) -> None:
    """1차 오탐 — `기준` 낱말 제외·줄바꿈 경계가 막음(관측 제외 없이)."""
    assert _amount_lines(USD, text, summary=summary) == []


@pytest.mark.parametrize("summary", [False, True])
def test_observation_number_then_modifier_is_conservative_unparsed(summary: bool) -> None:
    """알고 남김(06·09): 관측값 숫자 뒤 꾸밈 낱말 + 통화 → UNPARSED. 보수적 실패가 조용한 통과보다 나음."""
    lines = _amount_lines(USD, "모델 관측값은 31 신규 미국 달러 입금", summary=summary)
    assert [c.reason for c in lines] == [CheckReason.UNPARSED]


# ---------- 추가 검토 4차 — 끊긴 숫자 토큰: 날짜면 결과 없음, 그 밖은 UNPARSED ----------


@pytest.mark.parametrize("summary", [False, True])
@pytest.mark.parametrize(
    "text",
    ["합계는 -945831.63 일본국 엔(JPY)임", "합계 +945831.63 일본국 엔", "합계 1,42,750.50 일본국 엔"],
)
def test_broken_number_token_is_unparsed(text: str, summary: bool) -> None:
    lines = _amount_lines(JPY, text, summary=summary)
    assert [c.reason for c in lines] == [CheckReason.UNPARSED]


@pytest.mark.parametrize("summary", [False, True])
@pytest.mark.parametrize("text", ["2022-09-02 일본국 엔 입금", "2022-09-02 입금 미국 달러 합계"])
def test_date_number_stays_no_result(text: str, summary: bool) -> None:
    assert _amount_lines(USD, text, summary=summary) == []


# ---------- 추가 검토 5차 — 금액 판정은 기존 파서(parse_before) 그대로 ----------


@pytest.mark.parametrize("summary", [False, True])
@pytest.mark.parametrize(
    "text",
    [
        "합계는 3억 일본국 엔(JPY)임",
        "합계는 3억 2천만 일본국 엔(JPY)임",
        "합계 -3억 일본국 엔",
        "합계 삼억 일본국 엔",
        "합계 약 3억 일본국 엔",
    ],
)
def test_korean_unit_amount_is_unparsed(text: str, summary: bool) -> None:
    lines = _amount_lines(JPY, text, summary=summary)
    assert [c.reason for c in lines] == [CheckReason.UNPARSED]
