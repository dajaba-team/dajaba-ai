"""질문 답변 전제·방향 평가 세트 11개 — 모양·픽스처·판정 규칙 (SCRUM-358, 정본 docs/str/08).

판정 예시 답은 손으로 만든 문장(녹화 아님). 기준선·다시 재기 결과는 08 표에.
"""

from __future__ import annotations

import json
import re

import pytest
import tools.record as record
import tools.record_ask_answer as record_answer
from tools import ask_premise_judge as judge

from aml_ai.shared.infrastructure.llm_client import LlmResult, recording_key
from aml_ai.shared.schemas.str import Direction, Facts
from aml_ai.str.domain.constants_ask import ASK_PLAN_PROMPT
from tests.conftest import FIXTURES, load_json

ITEMS = load_json(judge.PREMISE_SET)["items"]
BASE = load_json(FIXTURES / "ask_eval_set.json")["items"]


def _item(item_id: str) -> dict:
    return next(i for i in ITEMS if i["id"] == item_id)


def test_eleven_items_fixed_shape() -> None:
    assert [i["id"] for i in ITEMS] == ["P1", "P2", "P3", "P4", "P5", "P6", "D1", "D2", "D3", "D4", "D5"]
    assert {i["premise"] for i in ITEMS[:6]} == {"WRONG"} and {i["premise"] for i in ITEMS[6:]} == {"OK"}
    assert all(i["expected_kind"] == "FACT" and i["judge"]["right_all"] for i in ITEMS)


def test_questions_unique_across_both_sets() -> None:
    """계획 녹화 키는 질문에만 달림 — 같은 문장이면 기존 18개 녹화를 덮어씀."""
    questions = [i["question"] for i in BASE + ITEMS]
    assert len(questions) == len(set(questions))


@pytest.mark.parametrize("it", ITEMS, ids=lambda i: i["id"])
def test_fixture_parses_and_regex_compiles(it: dict) -> None:
    Facts.model_validate(load_json(FIXTURES / f"facts_{it['facts_case']}.json"))
    for pattern in it["judge"]["right_all"] + it["judge"]["wrong_any"]:
        re.compile(pattern)


def test_mixed_fixture_shape() -> None:
    """입금 상대 2 · 출금 상대 3 · 겹친 계좌 1 → 전체 4 — 어느 방향 값·합 5 와도 다름."""
    f = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
    assert (f.inbound.count, f.outbound.count, f.counterparties.count) == (2, 3, 4)
    assert f.direction is Direction.MIXED


@pytest.mark.parametrize(
    ("item_id", "answer", "mark"),
    [
        ("P1", "이 케이스에 들어온 거래는 없어요. 보낸 상대 계좌는 3개예요.", judge.RIGHT),
        ("P1", "입금 상대는 계좌 3개로 보여요.", judge.WRONG),
        ("P1", "입금 상대 계좌 3개 가운데 들어온 거래는 없어요.", judge.HOLD),
        ("P2", "출금 거래만 3건 있어요.", judge.HOLD),
        ("P5", "EUR 로 들어온 거래는 없어요. 들어온 돈은 42750.50 USD 예요.", judge.RIGHT),
        ("D3", "입금 상대 계좌는 2개예요.", judge.RIGHT),
        ("D3", "입금 상대 계좌는 4개예요.", judge.WRONG),
        ("D5", "입금은 2건, 출금은 3건이에요.", judge.RIGHT),
        ("D5", "거래는 모두 5건이에요.", judge.WRONG),
    ],
)
def test_verdict_answered(item_id: str, answer: str, mark: str) -> None:
    assert judge.verdict(_item(item_id), "ANSWERED", answer) == mark


def test_not_answered_passes_only_wrong_premise() -> None:
    for status in ("NO_DATA", "UNVERIFIED"):
        assert judge.verdict(_item("P1"), status, None) == judge.NOT_ANSWERED
    assert judge.passed(_item("P1"), judge.NOT_ANSWERED)
    assert not judge.passed(_item("D3"), judge.NOT_ANSWERED)
    assert judge.verdict(_item("P1"), "OUT_OF_SCOPE", None) == judge.OTHER
    assert not judge.passed(_item("P1"), judge.OTHER)


def test_target_lines() -> None:
    rows = [judge.Row(_item("P1"), judge.WRONG, 9000), judge.Row(_item("D1"), judge.RIGHT, 21000)]
    lines = judge.target_lines(rows)
    assert lines[0].startswith("틀림 1/2") and "방향 질문 맞음 1/1" in lines[3]
    assert "21000ms" in lines[4]


def test_plan_saved_only_when_new(tmp_path, monkeypatch) -> None:
    """--premise — 계획 녹화가 없을 때만 저장, 있으면 그대로(덮어쓰기 0)."""
    monkeypatch.setattr(record, "RECORDED", tmp_path)
    monkeypatch.setattr(record_answer, "RECORDED", tmp_path)
    call = (
        {"system": "s", "user": "u"},
        LlmResult(text='{"x": 1}', model="m", tokens_in=1, tokens_out=1, latency_ms=1),
    )
    path = tmp_path / ASK_PLAN_PROMPT / f"{recording_key('s', 'u')}.json"
    assert record_answer._save_plan_if_new(call) is True
    assert json.loads(path.read_text(encoding="utf-8"))["text"] == '{"x": 1}'
    path.write_text('{"text": "old", "model": "m"}', encoding="utf-8")
    assert record_answer._save_plan_if_new(call) is False
    assert json.loads(path.read_text(encoding="utf-8"))["text"] == "old"
