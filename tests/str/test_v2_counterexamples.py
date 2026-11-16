"""SCRUM-131 (3/n) — v2 자유 문장 반례 측정 (docs/str/08 "v2 반례 측정"). LLM·DB 0.

현재 06 검사기 동작을 고정한다(검사기는 고치지 않음). `silent` 은 숫자가 있는데 코드 검사가 놓친 것 —
06 한계 / v4 는 카탈로그로 막음. `not_target` 은 숫자 없는 반례 — v2 는 평가자 기준 몫(확률적, 미측정).
"""

from __future__ import annotations

from collections import Counter

import pytest

from aml_ai.shared.schemas.str import Facts, SectionV2
from tests.str.test_v4_catalog_lint import SENTENCES as CATALOG_SENTENCES
from tests.str.v2_counterexamples_support import (
    COUNTEREXAMPLES,
    Counterexample,
    facts_of,
    insert,
    measure,
    v2_body,
)
from tests.str.v4_catalog_lint import lint

BY_ID = {ce.cid: ce for ce in COUNTEREXAMPLES}
JUDGE_CRITERIA = {"NO_SPECULATION", "NO_UNSUPPORTED_CLAIM"}  # judge_v2 기준 이름

# 반례마다 "이 facts 에서 그 문장이 거짓" — 측정 전에 손으로 확인한 조건
FALSE_IN: dict[str, object] = {
    "N1": lambda f: f.counterparties.count != 3,
    "N2": lambda f: all(c.currency != "KRW" for c in f.inbound.by_currency),
    "N3": lambda f: f.outbound.count != 2,
    "N4": lambda f: all(r.max != "3.50" for r in f.amount_range),
    "N5": lambda f: f.period.start.month != 9 or f.period.start.day != 9,
    "F1": lambda f: (
        f.counterparty_banks.same_bank_accounts > 0 or f.period.start.date() != f.period.end.date()
    ),
    "F2": lambda f: f.inbound.count > 0,
    "F3": lambda f: f.counterparty_banks.same_bank_accounts > 0,
    "F4": lambda f: f.period.start != f.period.end,
    "S1": lambda f: all(o.baseline is None for o in f.observations),  # "급격히 증가" 근거(비교 기준값) 없음
    "P1": lambda f: f.paths is None,
    "P2": lambda f: f.inbound.count == 0,
    "A1": lambda f: any(o.baseline is not None for o in f.observations),
    "A2": lambda f: f.internal.count > 0,
}

# 측정 결과(현재 동작, 11/17) — 08 표·09 숫자와 같은 값. 잡힘 0 · 조용한 통과 6 · 검사 대상 아님 8
EXPECTED: dict[str, str] = {
    **dict.fromkeys(("N1", "N2", "N3", "N4", "N5", "A2"), "silent"),  # 06 한계 / v4 는 카탈로그로 막음
    **dict.fromkeys(("F1", "F2", "F3", "F4", "S1", "P1", "P2", "A1"), "not_target"),  # v2 평가자 몫(미측정)
}


def test_fourteen_counterexamples_with_unique_ids() -> None:
    assert len(COUNTEREXAMPLES) == 14 and len(BY_ID) == 14
    assert Counter(ce.group for ce in COUNTEREXAMPLES) == {
        "숫자 우회": 5,
        "플래그 변형": 4,
        "추측": 1,
        "전제 위반": 2,
        "부재·범위 과장": 2,
    }


def test_body_is_seven_section_v2_record() -> None:
    body = v2_body()
    assert [s.section for s in body] == list(SectionV2)
    assert all(s.text for s in body)


def test_insert_appends_only_to_target_section() -> None:
    body = v2_body()
    out = insert(body, SectionV2.PLACE, "반례 문장.")
    for before, after in zip(body, out, strict=True):
        if before.section is SectionV2.PLACE:
            assert after.text == before.text + " 반례 문장." and after.cites == before.cites
        else:
            assert after == before
    assert body == v2_body()  # 원본 안 바뀜


@pytest.mark.parametrize("cid", list(BY_ID))
def test_sentence_is_false_in_its_facts(cid: str) -> None:
    facts: Facts = facts_of(BY_ID[cid].facts)
    assert FALSE_IN[cid](facts), cid  # type: ignore[operator]


@pytest.mark.parametrize("cid", list(BY_ID))
def test_category_follows_number_and_new_failures(cid: str) -> None:
    ce, out = BY_ID[cid], measure(BY_ID[cid])
    if out.new_failures:
        assert out.category == "caught"
    else:
        assert out.category == ("silent" if ce.has_number else "not_target")
    assert ce.judge in JUDGE_CRITERIA and ce.guard_note


def test_summary_counts() -> None:
    assert Counter(EXPECTED.values()) == {"silent": 6, "not_target": 8}


@pytest.mark.parametrize(
    ("sentence", "section", "failure"),
    [  # 대조 — 같은 자리에 아라비아 숫자로 쓰면 잡힘(측정이 실제로 새 실패를 셈)
        ("입금 합계는 99.00 USD임.", SectionV2.METHOD, "AMOUNT_MATCH:MISMATCH"),
        ("출금은 2건임.", SectionV2.METHOD, "COUNT_MATCH:MISMATCH"),
        ("첫 입금은 2022-09-09 에 이루어짐.", SectionV2.DATE, "DATE_MATCH:MISMATCH"),
        ("상대 계좌는 5개임.", SectionV2.PLACE, "COUNT_MATCH:MISMATCH"),
    ],
)
def test_control_with_arabic_digits_is_caught(sentence: str, section: SectionV2, failure: str) -> None:
    ce = Counterexample(
        "C", "대조", section, sentence, "fixture:fan_in", True, "NO_UNSUPPORTED_CLAIM", "claims", "-"
    )
    out = measure(ce)
    assert out.category == "caught" and out.new_failures == [failure]


@pytest.mark.parametrize("cid", list(BY_ID))
def test_current_behaviour_is_fixed(cid: str) -> None:
    """06 한계 / v4 는 카탈로그로 막음 — silent 도 현재 동작 그대로 단언(검사기 안 넓힘)."""
    assert measure(BY_ID[cid]).category == EXPECTED[cid]


@pytest.mark.parametrize("cid", [ce.cid for ce in COUNTEREXAMPLES if ce.guard == "lint"])
def test_v4_catalog_lint_blocks_the_sentence(cid: str) -> None:
    assert lint(BY_ID[cid].sentence), cid


@pytest.mark.parametrize("cid", [ce.cid for ce in COUNTEREXAMPLES if ce.guard == "closed"])
def test_v4_has_no_such_sentence_and_lint_misses_it(cid: str) -> None:
    """v4 는 자유 문장 경로가 없어 이 문장이 나올 수 없음 — 카탈로그 렌더 문장에 없음. 린트 미검출은 기록(131 3/n)."""
    sentence = BY_ID[cid].sentence
    assert all(sentence not in text for _, text in CATALOG_SENTENCES)
    assert lint(sentence) == []  # 카탈로그 작성용 린트의 빈틈 — 바꾸면 이 줄과 guard 를 같이 고침
