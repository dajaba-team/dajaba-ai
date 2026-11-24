"""기간 한정어 추가 검토 1 회귀 — 검토가 쓴 문장 그대로 (SCRUM-412, 정본 docs/str/06·08). LLM 없음(가짜 LLM).

틀린 숫자가 ANSWERED 로 새는 것은 막힘으로, 한정어가 아닌 낱말(`주거래`·`주체`·`주식`)은 통과로 고정.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
CASE_NO = ask_request().case_no
IN_COUNT = "{{inbound.count|이}} 확인돼요."
QUALIFIER = "질문 한정어와 다른 집계"


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
    assert res.code_checks[0].draft_value.startswith(QUALIFIER)


# ---------- 질문 쪽 — 새던 표현 (high 1·2·4·5) ----------


@pytest.mark.parametrize(
    "question",
    [
        "이 계좌의 9/7자 입금 건수는?",  # 1 — `의` 뒤 예외 뺌
        "9/7 이상거래 중 입금은 몇 건이야?",  # 1 — `이상` 예외 뺌
        "지난주로 한정하면 입금이 몇 건이야?",  # 2 — `지난`/`이번` 뒤 `주` 조사 무관
        "９　／　７ 입금 건수는?",  # 4 — 전각 공백
        "2022‑09‑07 입금 건수는?",  # 4 — U+2011 하이픈
        "지난 24시간 동안 입금은 몇 건이야?",  # 5
        "지난 두 달간 입금은 몇 건이야?",  # 5
        "지난 달 입금 건수는?",  # 5 — 띄어쓰기
    ],
)
def test_review1_question_qualifiers_block(question: str) -> None:
    _blocked(question, IN_COUNT)


# ---------- 절 쪽 (high 2·3, medium 6) ----------


def test_review1_p6_clause_with_jinanju_ro_blocks() -> None:
    _blocked(
        "9/7 입금 건수는?", "이 케이스는 {{period|이며}}, 지난주로 한정하면 {{inbound.count|이}} 확인돼요."
    )


def test_review1_clause_period_word_blocks_without_question_qualifier() -> None:
    _blocked("입금 건수는?", "이 케이스는 {{period|이며}}, 지난주에는 {{inbound.count|이}} 확인돼요.")


@pytest.mark.parametrize("stop", ["．", "。", "."])
def test_review1_fullwidth_stop_ends_sentence(stop: str) -> None:
    _blocked(
        "9/7 입금 건수는?",
        f"이 케이스는 {{{{period|예요}}}}{stop} 해당 날짜의 {{{{inbound.count|이}}}} 확인돼요.",
    )


# ---------- 알고 남김 — 막힘(안전 쪽, medium 7 · high 1 분수) ----------


def test_review1_excluded_period_still_blocks() -> None:
    _blocked("지난주 말고 이 케이스 기간 전체의 입금은 몇 건이야?", IN_COUNT)


def test_review1_ratio_question_blocks() -> None:
    _blocked(
        "입금과 출금의 건수 비율이 2/3인지 두 건수를 알려줘",
        "{{inbound.count|이}} 확인되고, {{outbound.count|이}} 확인돼요.",
    )


# ---------- 통과 유지 — `주` 가 든 낱말·식별자 끝 숫자 (high 2) ----------


@pytest.mark.parametrize(
    ("question", "answer"),
    [
        ("10_8000EBD30 주거래 계좌의 입금 건수는?", IN_COUNT),
        ("이 계좌로 입금한 주체들의 달러 입금 합계는?", "{{inbound.amount.USD|이}} 확인돼요."),
        (f"{CASE_NO} 주거래 계좌의 입금 건수는?", IN_COUNT),
        ("한 주체가 입금한 건수는?", IN_COUNT),
        ("주식 거래 입금 건수는?", IN_COUNT),
    ],
)
def test_review1_ju_words_stay_answered(question: str, answer: str) -> None:
    assert _ask(question, answer).status is AskStatus.ANSWERED, question
