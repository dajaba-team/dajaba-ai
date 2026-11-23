"""질문 답변 LLM 출력 스키마 — AskPlanOut·AskAnswerOut (SCRUM-290, 정본 docs/str/05 ask_plan_v1·ask_answer_v1)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from aml_ai.shared.infrastructure.openai_responses import json_schema_for
from aml_ai.shared.schemas.str import llm_output_model
from aml_ai.shared.schemas.str.ask_llm import AskAnswerOut, AskAnswerOutV3, AskBundle, AskPlanOut

EMOJI = "😀"  # UTF-16 2단위


def _plan(**kw) -> AskPlanOut:
    body = {"kind": "FACT", "out_of_scope_reason": None, "bundles": ["flows"], **kw}
    return AskPlanOut.model_validate_json(json.dumps(body))


def test_bundle_names_are_the_eight() -> None:
    assert [b.value for b in AskBundle] == [
        "subject",
        "flows",
        "counterparties",
        "formats",
        "paths",
        "observations",
        "score_reasons",
        "rule_facts",
    ]


@pytest.mark.parametrize(
    "kw",
    [
        {},
        {"kind": "WHY", "bundles": ["score_reasons", "observations", "rule_facts"]},
        {"kind": "OUT_OF_SCOPE", "out_of_scope_reason": "JUDGMENT", "bundles": []},
    ],
    ids=["fact-1", "why-3", "oos"],
)
def test_plan_valid(kw: dict) -> None:
    _plan(**kw)


@pytest.mark.parametrize(
    "kw",
    [
        {"bundles": ["nope"]},
        {"bundles": []},
        {"bundles": ["flows", "subject", "paths", "formats"]},
        {"bundles": ["flows", "flows"]},
        {"out_of_scope_reason": "JUDGMENT"},
        {"kind": "OUT_OF_SCOPE", "out_of_scope_reason": None, "bundles": []},
        {"kind": "OUT_OF_SCOPE", "out_of_scope_reason": "EDIT_REQUEST", "bundles": ["flows"]},
        {"kind": "MAYBE"},
    ],
    ids=["unknown", "zero", "four", "dup", "fact+reason", "oos-no-reason", "oos+bundle", "bad-kind"],
)
def test_plan_invalid(kw: dict) -> None:
    with pytest.raises(ValidationError):
        _plan(**kw)


def _answer(**kw) -> AskAnswerOut:
    body = {
        "answerable": True,
        "answer": "입금 상대 계좌는 3개예요.",
        "cites": ["counterparties.count"],
        **kw,
    }
    return AskAnswerOut.model_validate_json(json.dumps(body, ensure_ascii=False))


def test_answer_valid_and_boundary() -> None:
    _answer()
    _answer(answer="가" * 398 + EMOJI)  # 400
    out = _answer(answer=" 앞 공백 보존 ")
    assert out.answer == " 앞 공백 보존 "
    _answer(answerable=False, answer=None, cites=[])
    _answer(answerable=False, answer="모르겠어요", cites=["x"])  # 서비스가 무시


@pytest.mark.parametrize(
    "kw",
    [
        {"cites": []},
        {"answer": None},
        {"answer": "   "},
        {"answer": "가" * 399 + EMOJI},  # 401
        {"cites": ["a", "a"]},
        {"cites": [" "]},
    ],
    ids=["no-cites", "no-answer", "blank", "401", "dup-cite", "blank-cite"],
)
def test_answer_invalid_when_answerable(kw: dict) -> None:
    with pytest.raises(ValidationError):
        _answer(**kw)


def test_output_models_registered_for_structured_output() -> None:
    assert llm_output_model("ask_plan_v1") is AskPlanOut
    assert llm_output_model("ask_answer_v1") is AskAnswerOut
    assert (
        llm_output_model("ask_answer_v2") is AskAnswerOut
    )  # HttpLlmClient 가 tag 로 Structured Output 스키마를 찾음
    schema = json_schema_for(AskPlanOut, name="ask_plan_v1")["schema"]
    assert set(schema["required"]) == {"kind", "out_of_scope_reason", "bundles"}
    json_schema_for(AskAnswerOut, name="ask_answer_v1")
    assert llm_output_model("ask_answer_v3") is AskAnswerOutV3  # SCRUM-362 — cites 없음
    assert llm_output_model("ask_answer_v4") is AskAnswerOutV3  # v3 규칙 5·9 만 다름
    v3 = json_schema_for(AskAnswerOutV3, name="ask_answer_v3")["schema"]
    assert set(v3["required"]) == {"answerable", "answer"} and "cites" not in v3["properties"]


def _answer_v3(**kw) -> AskAnswerOutV3:
    body = {"answerable": True, "answer": "{{inbound.count|이에요}}", **kw}
    return AskAnswerOutV3.model_validate_json(json.dumps(body, ensure_ascii=False))


def test_answer_v3_valid_and_boundary() -> None:
    _answer_v3()
    _answer_v3(answer="가" * 398 + EMOJI)  # 400 — 렌더링 뒤 길이는 06 검사
    _answer_v3(answerable=False, answer=None)
    _answer_v3(answerable=False, answer="모르겠어요")  # 서비스가 무시


@pytest.mark.parametrize(
    "kw",
    [{"answer": None}, {"answer": "   "}, {"answer": "가" * 399 + EMOJI}, {"cites": ["inbound.count"]}],
    ids=["no-answer", "blank", "401", "v2-cites"],
)
def test_answer_v3_invalid(kw: dict) -> None:
    with pytest.raises(ValidationError):
        _answer_v3(**kw)
