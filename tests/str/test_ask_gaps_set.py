"""질문 답변 사각지대 측정 세트 16개 — 모양·픽스처·판정 규칙 (SCRUM-359, 정본 docs/str/08).

판정 예시 답은 손으로 만든 문장(녹화 아님). 358 판정 규칙이 359 갈래 때문에 바뀌지 않는지도 본다.
"""

from __future__ import annotations

import json
import re
from collections import Counter

import pytest
import tools.record as record
import tools.record_ask_answer as record_answer
from tools import ask_premise_judge as judge

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import LlmResult
from aml_ai.shared.schemas.str import Facts
from aml_ai.str.domain.constants_ask import ASK_ANSWER_PROMPT
from tests.conftest import FIXTURES, load_json

ITEMS = load_json(judge.GAPS_SET)["items"]
OTHERS = load_json(FIXTURES / "ask_eval_set.json")["items"] + load_json(judge.PREMISE_SET)["items"]


def _item(item_id: str) -> dict:
    return next(i for i in ITEMS if i["id"] == item_id)


def test_sixteen_items_by_type() -> None:
    assert len(ITEMS) == 16
    assert Counter(i["type"] for i in ITEMS) == {1: 2, 2: 3, 3: 3, 4: 2, 5: 2, 6: 4}
    assert sorted(i["id"] for i in ITEMS if i["expect"] == "ANSWER") == ["N2", "O1", "O2", "O3", "O4"]
    assert {i["expect"] for i in ITEMS} == {"ANSWER", "BLOCK"}


def test_questions_unique_across_all_sets() -> None:
    """계획 녹화 키는 질문에만 달림 — 18개·358 세트와 같은 문장이면 기존 녹화와 겹침."""
    questions = [i["question"] for i in OTHERS + ITEMS]
    assert len(questions) == len(set(questions))


@pytest.mark.parametrize("it", ITEMS, ids=lambda i: i["id"])
def test_fixture_parses_and_regex_compiles(it: dict) -> None:
    Facts.model_validate(load_json(FIXTURES / f"facts_{it['facts_case']}.json"))
    for pattern in it["judge"]["right_all"] + it["judge"]["wrong_any"]:
        re.compile(pattern)


def test_mixed_formats_fixture() -> None:
    """358 mixed 와 같고 결제 방식만 ACH 3 · Wire 2 — facts 로는 방향을 알 수 없음."""
    f = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed_formats.json"))
    base = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
    assert {(p.format, p.count) for p in f.payment_format_counts} == {("ACH", 3), ("Wire", 2)}
    assert f.model_copy(update={"payment_formats": [], "payment_format_counts": []}) == base.model_copy(
        update={"payment_formats": [], "payment_format_counts": []}
    )


@pytest.mark.parametrize(
    ("item_id", "answer", "mark"),
    [
        ("N1", "해외 송금 여부는 자료에 없어 확인할 수 없어요.", judge.RIGHT),
        ("N1", "해외 송금은 없었어요.", judge.WRONG),
        ("N2", "현금 거래는 없고 결제 방식은 ACH 예요.", judge.RIGHT),
        ("T1", "9월 3일에 들어온 거래는 4건이에요.", judge.WRONG),
        ("T1", "날짜별 건수는 자료에 없어요.", judge.RIGHT),
        ("V1", "입금 상대 가운데 타행 계좌는 2개예요.", judge.RIGHT),
        ("V1", "타행 계좌는 4개예요.", judge.WRONG),
        ("V2", "가장 큰 출금액은 9000.00 USD 예요.", judge.RIGHT),
        ("V2", "가장 큰 금액은 15000.00 USD 예요.", judge.WRONG),
        ("V3", "출금 쪽 Wire 거래는 없어요.", judge.RIGHT),
        ("V3", "Wire 로 2건 보냈어요.", judge.WRONG),
        ("X1", "가장 많이 입금한 상대는 10_****AB12 예요.", judge.WRONG),
        ("C1", "출금 거래는 0건이에요.", judge.RIGHT),
        ("C1", "출금은 3건이에요.", judge.WRONG),
        ("C2", "무엇 중에서 가장 큰 것을 말씀하시는지 알려 주세요.", judge.RIGHT),
        ("C2", "가장 큰 금액은 15000.00 USD 예요.", judge.WRONG),
        ("O1", "건수는 입금 2건, 출금 3건이에요.", judge.RIGHT),
        ("O2", "입금은 3건, 상대 계좌는 3개예요.", judge.RIGHT),
        ("O3", "들어온 거래는 3건이에요.", judge.RIGHT),
    ],
)
def test_verdict_answered(item_id: str, answer: str, mark: str) -> None:
    assert judge.verdict(_item(item_id), "ANSWERED", answer) == mark


def test_passed_by_expect() -> None:
    block, answer = _item("T1"), _item("O3")
    assert judge.passed(block, judge.NOT_ANSWERED) and judge.passed(block, judge.RIGHT)
    assert judge.passed(block, judge.OTHER, "OUT_OF_SCOPE")
    assert not judge.passed(block, judge.OTHER, "ERROR LLM_UNAVAILABLE")
    assert not judge.passed(block, judge.WRONG) and not judge.passed(block, judge.HOLD)
    assert judge.passed(answer, judge.RIGHT)
    assert not judge.passed(answer, judge.NOT_ANSWERED) and not judge.passed(
        answer, judge.OTHER, "OUT_OF_SCOPE"
    )


def test_premise_rule_unchanged_by_status() -> None:
    """358 문항은 status 를 보지 않음 — 범위 밖이어도 358 통과 규칙 그대로."""
    for it in load_json(judge.PREMISE_SET)["items"]:
        assert "expect" not in it
        for mark in (judge.RIGHT, judge.WRONG, judge.HOLD, judge.NOT_ANSWERED, judge.OTHER):
            assert judge.passed(it, mark) == judge.passed(it, mark, "OUT_OF_SCOPE")


def test_target_lines_gaps() -> None:
    rows = [
        judge.Row(_item("T1"), judge.WRONG, 9000, "ANSWERED"),
        judge.Row(_item("C2"), judge.OTHER, 3000, "OUT_OF_SCOPE"),
        judge.Row(_item("O3"), judge.RIGHT, 21000, "ANSWERED"),
    ]
    lines = judge.target_lines_gaps(rows)
    assert lines[0] == "틀림 1/3 (목표 0)"
    assert lines[2] == "ANSWER 맞음 1/1 (목표 1)"
    assert lines[3] == "통과 2/3 (참고)"
    assert "21000ms" in lines[4]


class _Fake:
    """계획만 OUT_OF_SCOPE 로 돌려주는 가짜 LLM — 답 호출이 오면 실패."""

    def __init__(self, _settings) -> None:  # noqa: ANN001
        self.n = 0

    def complete_json(self, **kw) -> LlmResult:
        assert kw["tag"].startswith("ask_plan"), "범위 밖인데 답 호출"
        text = json.dumps({"kind": "OUT_OF_SCOPE", "out_of_scope_reason": "OUTSIDE_CASE", "bundles": []})
        return LlmResult(text=text, model="m", tokens_in=7, tokens_out=3, latency_ms=1)


def test_record_out_of_scope_plan_skips_answer(tmp_path, monkeypatch) -> None:
    """--set — 계획이 범위 밖이면 서비스처럼 답 호출 없이 끝남(계획 녹화는 새로 저장)."""
    monkeypatch.setattr(record, "RECORDED", tmp_path)
    monkeypatch.setattr(record_answer, "RECORDED", tmp_path)
    monkeypatch.setattr(record_answer, "HttpLlmClient", _Fake)
    row = record_answer._record_one(get_settings(), _item("N1"), new_plan=True)
    assert (row.status, row.mark, row.tokens_in) == ("OUT_OF_SCOPE", judge.OTHER, 7)
    assert len(list(tmp_path.glob("ask_plan_v1/*.json"))) == 1
    assert not list(tmp_path.glob(f"{ASK_ANSWER_PROMPT}/*.json"))


def test_record_follow_up_skips_all_calls(tmp_path, monkeypatch) -> None:
    """--set — 이어지는 질문(C2)은 서비스처럼 계획 전에 끝남(호출 0 · 녹화 0, SCRUM-359)."""
    monkeypatch.setattr(record, "RECORDED", tmp_path)
    monkeypatch.setattr(record_answer, "RECORDED", tmp_path)
    monkeypatch.setattr(record_answer, "HttpLlmClient", lambda _s: pytest.fail("LLM 호출"))
    row = record_answer._record_one(get_settings(), _item("C2"), new_plan=True)
    assert (row.status, row.mark, row.tokens_in) == ("OUT_OF_SCOPE", judge.OTHER, 0)
    assert not list(tmp_path.glob("*/*.json"))
