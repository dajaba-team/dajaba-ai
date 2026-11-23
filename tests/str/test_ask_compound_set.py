"""복합 WHY 세트(K1~K4) — 판정·녹화 도구 경로 (SCRUM-362 추가 검토 1 M2, 정본 docs/str/08). 가짜 LLM — 실제 호출 0."""

from __future__ import annotations

import json

import pytest
from tools import ask_premise_judge as judge
from tools import record, record_ask_answer

from aml_ai.shared.config import get_settings
from aml_ai.shared.infrastructure.llm_client import LlmResult
from aml_ai.str.domain.constants_ask import ASK_ANSWER_PROMPT, ASK_PLAN_PROMPT
from tests.conftest import load_json

ITEMS = {i["id"]: i for i in load_json(judge.COMPOUND_SET)["items"]}


def test_set_is_four_why_with_two_bundles() -> None:
    assert sorted(ITEMS) == ["K1", "K2", "K3", "K4"]
    assert all(i["expected"]["kind"] == "WHY" and len(i["expected"]["bundles"]) == 2 for i in ITEMS.values())


@pytest.mark.parametrize(
    ("cites", "status", "mark"),
    [
        (["typology", "paths.count"], "ANSWERED", judge.RIGHT),
        (["typology", "period"], "ANSWERED", judge.MISSING_BUNDLE),  # paths 키 없음
        (["paths.count"], "ANSWERED", judge.MISSING_BUNDLE),
        ([], "UNVERIFIED", judge.NOT_ANSWERED),
        ([], "NO_DATA", judge.NOT_ANSWERED),
    ],
)
def test_compound_mark_needs_a_slot_from_each_bundle(cites: list[str], status: str, mark: str) -> None:
    assert judge.compound_mark(ITEMS["K1"], status, cites) == mark


def test_targets_line() -> None:
    rows = [judge.Row(ITEMS[k], judge.RIGHT, 10, "ANSWERED") for k in ("K1", "K2", "K3")]
    rows.append(judge.Row(ITEMS["K4"], judge.NOT_ANSWERED, 20, "UNVERIFIED"))
    assert judge.target_lines_compound(rows)[:3] == [
        "ANSWERED 3/4 (목표 4)",
        "UNVERIFIED 1/4 (목표 0)",
        "두 묶음 자리표 3/4 (목표 4)",
    ]


class _Fake:
    """계획은 기대 계획, 답은 고정 원문(K1 — rule_facts 키 + paths 키)."""

    def __init__(self, _settings) -> None:  # noqa: ANN001
        pass

    def complete_json(self, **kw) -> LlmResult:
        if kw["tag"] == ASK_PLAN_PROMPT:
            e = ITEMS["K1"]["expected"]
            text = json.dumps({"kind": e["kind"], "out_of_scope_reason": None, "bundles": e["bundles"]})
        else:
            raw = "{{typology|으로}} 탐지된 경보로 보여요. {{paths.count|이}} 확인돼요."
            text = json.dumps({"answerable": True, "answer": raw}, ensure_ascii=False)
        return LlmResult(text=text, model="m", tokens_in=3, tokens_out=2, latency_ms=1)


def test_record_compound_item_marks_right_and_saves_to_tmp(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(record, "RECORDED", tmp_path)
    monkeypatch.setattr(record_ask_answer, "RECORDED", tmp_path)
    monkeypatch.setattr(record_ask_answer, "HttpLlmClient", _Fake)
    row = record_ask_answer._record_one(get_settings(), ITEMS["K1"], new_plan=True)
    assert (row.status, row.mark) == ("ANSWERED", judge.RIGHT)
    assert len(list(tmp_path.glob(f"{ASK_PLAN_PROMPT}/*.json"))) == 1
    assert len(list(tmp_path.glob(f"{ASK_ANSWER_PROMPT}/*.json"))) == 1


@pytest.fixture
def _no_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _replay(it: dict) -> tuple[str, str, int]:
    from tests.str.ask_recorded_support import facts_for, recorded
    from tests.str.ask_service_support import ask_request, build_service

    svc, _ = build_service(recorded(), facts=facts_for(it))
    res = svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))
    return (
        res.status.value,
        judge.compound_mark(it, res.status.value, list(res.cites)),
        res.generation_meta.latency_ms,
    )


@pytest.mark.parametrize("item_id", ["K1", "K2", "K3", "K4"])
def test_v6_replay_answered_with_both_bundles(item_id: str, _no_end_read) -> None:
    """08 "결과 — 복합 WHY 답" — 계획 v3·답 v6 녹화 재생: ANSWERED · 두 묶음 자리표 각 1개 이상."""
    status, mark, _ = _replay(ITEMS[item_id])
    assert (status, mark) == ("ANSWERED", judge.RIGHT)


def test_v6_replay_targets(_no_end_read) -> None:
    rows = [judge.Row(it, mark, 0, status) for it in ITEMS.values() for status, mark, _ in [_replay(it)]]
    assert judge.target_lines_compound(rows)[:3] == [
        "ANSWERED 4/4 (목표 4)",
        "UNVERIFIED 0/4 (목표 0)",
        "두 묶음 자리표 4/4 (목표 4)",
    ]
