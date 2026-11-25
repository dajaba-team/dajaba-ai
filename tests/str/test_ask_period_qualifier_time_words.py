"""기간 한정어 — 시간대·요일·날수·답 쪽 `해당 기간` (11/25 전체 점검, 정본 docs/str/06·08). LLM 없음(가짜 LLM).

facts 는 기간 전체 집계뿐 — `새벽`·`월요일`·`이틀` 로 물어도 기간 전체 건수가 ANSWERED 로 나가면 안 된다.
원칙 (A) 애매하면 막는다 · 기존 목록에 덧붙이기만(막는 쪽으로만).
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
IN_COUNT = "{{inbound.count|이}} 확인돼요."
QUALIFIER = "질문 한정어와 다른 집계"
P6_SAME = "질문하신 기간의 거래는 없어요. 이 케이스는 {{period|이며}}, {{inbound.count|이}} 확인돼요."
P6_SPLIT = "질문하신 기간의 거래는 없어요. 이 케이스는 {{period|이에요}}. 해당 기간에는 {{inbound.count|이}} 확인돼요."


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _ask(question: str, answer: str):  # noqa: ANN202
    llm = StubLlm([plan_text("FACT", None, ["flows"]), answer_text(True, answer)])
    svc, _ = build_service(llm, facts=MIXED)
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN"))


def _blocked(question: str, answer: str) -> None:
    res = _ask(question, answer)
    assert res.status is AskStatus.UNVERIFIED, (question, answer)
    assert res.code_checks[0].draft_value.startswith(QUALIFIER), (question, answer)


# ---------- 시간대 ----------


@pytest.mark.parametrize(
    "question",
    [
        "새벽에 들어온 거래는 몇 건이야?",
        "저녁에 들어온 거래는 몇 건이야?",
        "아침 입금은 몇 건이야?",
        "점심 무렵 입금은 몇 건이야?",
        "밤에 들어온 입금은 몇 건이야?",
        "심야 입금 건수는?",
        "야간에 들어온 입금은?",
        "자정 넘어 들어온 입금은?",
        "정오 전후 입금은 몇 건이야?",
        "낮에 들어온 입금은 몇 건이야?",
        "한낮 입금은 몇 건이야?",
        "영업시간 외 입금은 몇 건이야?",
        "근무 시간 입금은 몇 건이야?",
    ],
)
def test_time_of_day_is_period_qualifier(question: str) -> None:
    _blocked(question, IN_COUNT)


# ---------- 요일 ----------


@pytest.mark.parametrize(
    "question",
    [
        "월요일 입금은 몇 건이야?",
        "금요일에 들어온 입금은?",
        "일요일 입금 건수는?",
        "무슨 요일에 입금이 몇 건이야?",
        "평일 입금은 몇 건이야?",
        "주중 입금은 몇 건이야?",
        "공휴일 입금은 몇 건이야?",
        "영업일 기준 입금은 몇 건이야?",
    ],
)
def test_weekday_is_period_qualifier(question: str) -> None:
    _blocked(question, IN_COUNT)


# ---------- 날수 ----------


@pytest.mark.parametrize(
    "question",
    [
        "이틀 동안 입금은 몇 건이야?",
        "사흘간 입금은 몇 건이야?",
        "나흘 입금 건수는?",
        "닷새 동안 입금은?",
        "열흘간 입금은 몇 건이야?",
        "보름 동안 입금은 몇 건이야?",
        "하룻밤 사이 입금은 몇 건이야?",
        "전날 입금은 몇 건이야?",
        "다음 날 입금은 몇 건이야?",
        "이튿날 입금은 몇 건이야?",
    ],
)
def test_day_count_is_period_qualifier(question: str) -> None:
    _blocked(question, IN_COUNT)


# ---------- 영어 ----------


@pytest.mark.parametrize(
    "question",
    [
        "inbound count on Monday?",
        "inbound count at night?",
        "inbound count in the morning?",
        "weekend 입금은?",
    ],
)
def test_english_time_words_are_period_qualifier(question: str) -> None:
    _blocked(question, IN_COUNT)


# ---------- 답 쪽 — 새 낱말 · `해당 기간` ----------


@pytest.mark.parametrize(
    "answer", ["새벽에 {{inbound.count|이}} 확인돼요.", "평일 기준으로 {{inbound.count|이}} 확인돼요."]
)
def test_answer_period_word_blocks_without_question_qualifier(answer: str) -> None:
    _blocked("입금은 몇 건이야?", answer)


# `해당 기간` 은 질문에 한정어가 있을 때만 막음 — 한정어 없는 질문에선 기간 전체를 가리키는 정상 표현(11/25 전체 점검 후속 검토)
REFERRED = [
    "해당 기간에는 {{inbound.count|이}} 확인돼요.",
    "이 케이스는 {{period|이며}}, 해당 기간에 {{inbound.count|이}} 확인돼요.",
    "해당 기간 동안 입금은 {{inbound.count}}건이에요.",
]


@pytest.mark.parametrize("answer", REFERRED)
@pytest.mark.parametrize(
    "question", ["새벽에 들어온 거래는 몇 건이야?", "월요일 입금은 몇 건이야?", "9/7 입금 건수는?"]
)
def test_referred_period_blocks_with_question_qualifier(question: str, answer: str) -> None:
    _blocked(question, answer)


@pytest.mark.parametrize("answer", REFERRED[:2])
def test_referred_period_passes_without_question_qualifier(answer: str) -> None:
    assert _ask("입금은 몇 건이야?", answer).status is AskStatus.ANSWERED, answer


def test_referred_period_control_from_directive() -> None:
    """11/25 전체 점검 후속 검토 대조군 문장 그대로 — 한정어 없는 질문이라 `해당 기간` 으로 안 막힘."""
    res = _ask("입금은 몇 건이야?", "해당 기간 동안 입금은 {{inbound.count}}건이에요.")
    assert res.status is AskStatus.ANSWERED


def test_live_p6_shape_on_dawn_question_is_blocked() -> None:
    """실모델 P6 답 꼴(바로잡기 + 다른 문장 `해당 기간에는` 기간 전체 건수) — 새벽 질문에 ANSWERED 금지."""
    _blocked("새벽에 들어온 거래는 몇 건이야?", P6_SPLIT)


# ---------- 대조군 — 그대로 ANSWERED ----------


@pytest.mark.parametrize(
    "question",
    [
        "입금은 몇 건이야?",
        "들어온 거래는 몇 건이야?",
        "낮은 금액 입금도 있어? 입금 건수는?",
        "주요 입금은 몇 건이야?",
    ],
)
def test_plain_question_stays_answered(question: str) -> None:
    res = _ask(question, IN_COUNT)
    assert res.status is AskStatus.ANSWERED, question


@pytest.mark.parametrize("question", ["입금은 몇 건이야?", "2023년 1월에 들어온 거래는 몇 건이야?"])
def test_normal_p6_same_sentence_stays_answered(question: str) -> None:
    assert _ask(question, P6_SAME).status is AskStatus.ANSWERED, question
