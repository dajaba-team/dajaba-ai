"""AskRequest · 질문 답변 예시 — 규약 §5.4 제안 `/v1/cases/ask`, SCRUM-288 (docs/shared/01).

- 요청 = SummaryRequest 상속 + question (앞뒤 공백 안 자름 · 공백만 거부 · NFC·UTF-16 1~300)
- 예시 5개: 상태가 파일 이름과 같고, 요약 예시와 같은 케이스 값
- 응답 상태별 칸 규칙은 test_ask_response_rules
"""

from __future__ import annotations

import unicodedata

import pytest
from pydantic import ValidationError

from aml_ai.shared.schemas.str import ASK_QUESTION_MAX, AskRequest, AskResponse, AskStatus, SummaryRequest
from tests.conftest import EXAMPLES, load_json

EMOJI = "😀"  # UTF-16 2단위
NFD_GA = unicodedata.normalize("NFD", "가")  # 코드포인트 2개, NFC 뒤 1단위


@pytest.fixture
def body() -> dict:
    return {**load_json(EXAMPLES / "summary_request.json"), "question": "입금 상대가 몇 곳이야?"}


# ── 요청: 요약과 같은 6칸 + question ──


def test_valid_request(body: dict) -> None:
    AskRequest.model_validate(body)


def test_ask_request_is_summary_request() -> None:
    assert issubclass(AskRequest, SummaryRequest)


def test_request_rejects_unknown_field(body: dict) -> None:
    body["investigator_notes"] = "메모"  # 설계 5.2 — 메모는 보내지 않음
    with pytest.raises(ValidationError):
        AskRequest.model_validate(body)


@pytest.mark.parametrize("field", ["question", "reasons", "prior_alert_count", "evidence_transaction_ids"])
def test_request_required_fields(body: dict, field: str) -> None:
    del body[field]
    with pytest.raises(ValidationError):
        AskRequest.model_validate(body)


def test_reporting_institution_optional_like_summary(body: dict) -> None:
    del body["reporting_institution"]
    assert AskRequest.model_validate(body).reporting_institution is None


def test_to_facts_input_same_as_summary(body: dict) -> None:
    summary_body = {k: v for k, v in body.items() if k != "question"}
    ask = AskRequest.model_validate(body).to_facts_input()
    summary = SummaryRequest.model_validate(summary_body).to_facts_input()
    assert ask == summary


# ── question 경계 (NFC 뒤 UTF-16 코드 단위) ──


@pytest.mark.parametrize(
    "question",
    [
        "가",
        "가" * ASK_QUESTION_MAX,
        "가" * (ASK_QUESTION_MAX - 2) + EMOJI,  # 298 + 2 = 300
        NFD_GA * ASK_QUESTION_MAX,  # 코드포인트 600, NFC 300
        " " + "가" * (ASK_QUESTION_MAX - 1),  # 앞 공백도 센다 — 300
    ],
    ids=["1", "300", "298+emoji", "nfd-300", "space+299"],
)
def test_question_within_limit(body: dict, question: str) -> None:
    body["question"] = question
    AskRequest.model_validate(body)


@pytest.mark.parametrize(
    "question",
    [
        "",
        "   ",
        "\n\t ",
        "가" * (ASK_QUESTION_MAX + 1),
        "가" * (ASK_QUESTION_MAX - 1) + EMOJI,  # 299 + 2 = 301
        " " + "가" * ASK_QUESTION_MAX,  # 자르지 않으니 301
    ],
    ids=["empty", "spaces", "whitespace", "301", "299+emoji", "space+300"],
)
def test_question_rejected(body: dict, question: str) -> None:
    body["question"] = question
    with pytest.raises(ValidationError):
        AskRequest.model_validate(body)


def test_question_none_rejected(body: dict) -> None:
    body["question"] = None
    with pytest.raises(ValidationError):
        AskRequest.model_validate(body)


def test_question_keeps_surrounding_whitespace(body: dict) -> None:
    raw = "  입금 상대가 몇 곳이야?\n"
    body["question"] = raw
    assert AskRequest.model_validate(body).question == raw


def test_question_not_normalized(body: dict) -> None:
    """세기만 NFC — 값은 원문 그대로 (검증 수정본과 같음)."""
    body["question"] = NFD_GA * 3
    assert AskRequest.model_validate(body).question == NFD_GA * 3


# ── 예시 5개 — 상태·케이스 값 ──

STATUS_BY_FILE = {
    "ask_response_answered.json": AskStatus.ANSWERED,
    "ask_response_no_data.json": AskStatus.NO_DATA,
    "ask_response_unverified.json": AskStatus.UNVERIFIED,
    "ask_response_out_of_scope.json": AskStatus.OUT_OF_SCOPE,
}


@pytest.mark.parametrize(("name", "status"), STATUS_BY_FILE.items())
def test_example_status_matches_file(name: str, status: AskStatus) -> None:
    assert AskResponse.model_validate(load_json(EXAMPLES / name)).status is status


def test_example_request_is_summary_request_plus_question() -> None:
    ask = load_json(EXAMPLES / "ask_request.json")
    summary = load_json(EXAMPLES / "summary_request.json")
    assert set(ask) - set(summary) == {"question"}
    assert {k: v for k, v in ask.items() if k != "question"} == summary


@pytest.mark.parametrize("name", STATUS_BY_FILE)
def test_example_same_case(name: str) -> None:
    req = AskRequest.model_validate(load_json(EXAMPLES / "ask_request.json"))
    res = AskResponse.model_validate(load_json(EXAMPLES / name))
    assert res.case_no == req.case_no
    assert set(res.evidence_ids) <= set(req.evidence_transaction_ids)


def test_example_answered_uses_case_value() -> None:
    """★A 4 — 설계 예시 "31개" 가 아니라 이 케이스 값 3."""
    res = AskResponse.model_validate(load_json(EXAMPLES / "ask_response_answered.json"))
    assert res.answer is not None and "3개" in res.answer and "31" not in res.answer
    assert res.evidence_ids == [104221, 104233, 104301]
