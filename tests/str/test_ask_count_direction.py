"""질문 답변 상대 수·자행·타행 — 방향·근거 키 (SCRUM-358·359 · 추가 검토 2, 정본 docs/str/06 "질문 답변" 10번).

공용 COUNT_MATCH(초안·검증·요약)는 develop 그대로 — 방향을 안 본다(아래 마지막 두 테스트가 고정). 질문 답변만
`ask_direction` 이 숫자마다 값이 같은 인용 키 + 숫자를 바로 꾸미는 말의 방향으로 다시 판정한다.
양방향 픽스처 `facts_ask_mixed.json`: 입금 상대 2(타행 2) · 출금 상대 3(타행 3) · 전체 4(타행 4).
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import CheckReason, Facts, SectionV1
from aml_ai.str.domain import ask_checks
from aml_ai.str.domain.ask_bundles import ask_fact_keys
from tests.conftest import FIXTURES, load_json
from tests.str.verification_support import count, facts_fan_in

IN, OUT, TOTAL = (
    "counterparties_by_direction.inbound.count",
    "counterparties_by_direction.outbound.count",
    "counterparties.count",
)
IN_OTHER = "counterparties_by_direction.inbound.other_bank_accounts"


def _mixed() -> Facts:
    return Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))


def _count_rows(facts: Facts, answer: str, cites: list[str]):
    rows = ask_checks.run(facts, answer, cites, list(ask_fact_keys(facts)))
    return [c for c in rows if c.check.value == "COUNT_MATCH"]


@pytest.mark.parametrize(
    ("answer", "cites", "match", "reason"),
    [
        ("전체 상대 중 입금 상대는 계좌 2개예요.", [IN], True, None),  # 검토 2 재현 — `중` 뒤 명사구가 방향
        ("전체 상대 중 입금 상대는 계좌 4개예요.", [TOTAL], False, CheckReason.MISMATCH),
        (
            "수취인 계좌는 모두 3개이며 받은 금액은 서로 달라요.",
            [OUT],
            True,
            None,
        ),  # 검토 2 재현 — 뒤 `받은` 못 덮음
        ("수취인 계좌는 모두 2개이며 받은 금액은 서로 달라요.", [IN], False, CheckReason.MISMATCH),
        ("3명의 수취인이 받은 금액은 서로 달라요.", [OUT], True, None),
        ("입금 상대 중 타행 계좌는 2개예요.", [IN_OTHER], True, None),  # 359 V1 모양 — `중` 앞 조각의 방향
        ("입금 상대는 2개예요.", [TOTAL], False, CheckReason.MISSING),  # 값은 맞는데 그 방향 키를 안 인용
        ("입금 상대는 계좌 4개로 보여요.", [TOTAL], False, CheckReason.MISMATCH),  # 346 발견 모양
        ("입출금 전체의 상대 계좌는 4개예요.", [TOTAL], True, None),  # 합친 표현이 바로 꾸밈 → 전체
        ("상대 계좌는 모두 4개예요.", [TOTAL], True, None),
    ],
)
def test_direction_and_supporting_key(answer: str, cites: list[str], match: bool, reason) -> None:  # noqa: ANN001
    (row,) = _count_rows(_mixed(), answer, cites)
    assert (row.match, row.reason) == (match, reason), row


def test_total_and_inbound_together_both_keys() -> None:
    """검토 2 재현 — 전체 4 와 입금 2 를 같이 말하고 두 키를 인용하면 둘 다 통과(전에는 전체 키가 거절됨)."""
    rows = _count_rows(_mixed(), "전체 상대는 계좌 4개예요. 입금 상대는 계좌 2개예요.", [TOTAL, IN])
    assert [r.match for r in rows] == [True, True]


def test_subset_inherits_previous_direction() -> None:
    rows = _count_rows(_mixed(), "입금 상대는 계좌 2개이고, 이 가운데 타행 계좌는 2개예요.", [IN, IN_OTHER])
    assert [r.match for r in rows] == [True, True]


def test_counterparty_as_sender_is_inbound() -> None:
    """검토 2 재현 — `상대 계좌 3개가 보낸 돈이 입금됐어요` 는 상대가 주어 → 대상 쪽 입금(fan_in 복사본, 입금 상대 3)."""
    facts = Facts.model_validate(load_json(FIXTURES / "facts_ask_fan_in.json"))
    (row,) = _count_rows(facts, "상대 계좌 3개가 보낸 돈이 입금됐어요.", [IN])
    assert row.match


@pytest.mark.parametrize(
    ("answer", "match"),
    [
        ("출금 상대 중 자행 계좌는 0개예요.", True),
        ("출금 상대 계좌는 0개예요.", True),
        ("출금 상대 계좌는 3개예요.", False),
    ],
)
def test_no_field_zero_side_is_exact_zero(answer: str, match: bool) -> None:
    """칸 없음(기준 픽스처) + 그 방향 0건 → {0} — 질문 답변에서만(추가 검토 1 M1 → 2 에서 질문 답변 쪽으로)."""
    (row,) = _count_rows(facts_fan_in(), answer, [TOTAL])
    assert row.match is match


def test_shared_count_match_is_develop_direction_blind() -> None:
    """공용 COUNT_MATCH 는 develop 그대로 — 상대 수의 방향을 안 보고 전체 {4} 와 대조(초안·검증·요약 결과 그대로)."""
    (row,) = count(_mixed(), SectionV1.WHAT_WHEN_WHERE, "입금 상대 계좌는 2개예요.")
    assert (row.match, row.source_value) == (False, "{4}")


def test_shared_count_match_review_draft_sentence() -> None:
    """검토 2 재현 — 저장 초안(칸 없음 fan_in)의 `상대 계좌 3개가 보낸 돈이 입금됐어요` 는 develop 처럼 {3} 통과."""
    (row,) = count(facts_fan_in(), SectionV1.WHAT_WHEN_WHERE, "상대 계좌 3개가 보낸 돈이 입금됐어요.")
    assert (row.match, row.source_value) == (True, "{3}")
