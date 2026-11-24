"""기간 한정어 추가 검토 2 회귀 — 검토가 쓴 문장 그대로 (SCRUM-412, 정본 docs/str/06·08). LLM 없음(가짜 LLM).

원칙 (A) 애매하면 막는다: `M/D` 예외 없음 · 답 전체 검사 · 기간과 무관한 키 허용 목록(그 밖은 집계) · 종결부호 상수 하나.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
PATHS = Facts.model_validate(load_json(FIXTURES / "facts_ask_paths.json"))
MULTI = Facts.model_validate(load_json(FIXTURES / "facts_multi_currency.json"))
IN_COUNT = "{{inbound.count|이}} 확인돼요."
QUALIFIER = "질문 한정어와 다른 집계"
STOPS = ("．", "！", "？", "。")


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _ask(question: str, answer: str, facts: Facts = MIXED, bundle: str = "flows"):  # noqa: ANN202
    llm = StubLlm([plan_text("FACT", None, [bundle]), answer_text(True, answer)])
    svc, _ = build_service(llm, facts=facts)
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN"))


def _blocked(question: str, answer: str, facts: Facts = MIXED, bundle: str = "flows") -> None:
    res = _ask(question, answer, facts, bundle)
    assert res.status is AskStatus.UNVERIFIED, (question, answer)
    assert res.code_checks[0].draft_value.startswith(QUALIFIER)


# ---------- high 1 — M/D 예외 없음 ----------


@pytest.mark.parametrize(
    "question", ["9/7,9/8 이틀간 입금은 몇 건이야?", "9/7 비중 계산용이야. 해당 날짜 입금 몇 건이야?"]
)
def test_review2_md_has_no_exception(question: str) -> None:
    _blocked(question, IN_COUNT)


# ---------- high 2 — 답 전체(자리표 밖 글 어디든) ----------


@pytest.mark.parametrize(
    "answer",
    ["지난주 기준이에요. {{inbound.count|이}} 확인돼요.", "직전 한 주에 {{inbound.count|이}} 확인돼요."],
)
def test_review2_period_word_anywhere_in_answer_blocks(answer: str) -> None:
    _blocked("입금 건수는?", answer)


@pytest.mark.parametrize("question", ["입금 건수는?", "9/7 입금 건수는?"])
def test_review2_normal_p6_answer_stays(question: str) -> None:
    answer = "질문하신 기간의 거래는 없어요. 이 케이스는 {{period|이며}}, {{inbound.count|이}} 확인돼요."
    assert _ask(question, answer).status is AskStatus.ANSWERED, question


# ---------- high 3 — 키 목록 뒤집기(경로·미등록 통화도 집계) ----------


def test_review2_paths_count_is_period_aggregate() -> None:
    _blocked("9/7에 확인된 거래 경로는 몇 개야?", "{{paths.count|이}} 확인돼요.", PATHS, "paths")


def test_review2_unmapped_currency_is_period_aggregate() -> None:
    _blocked("9/7의 Peso Uruguay 거래 건수는?", "{{unmapped_currencies.Peso Uruguay|이}} 확인돼요.", MULTI)


# ---------- high 4 — 수 + 주(조사 무관) · 직전 · N시간 ----------


@pytest.mark.parametrize(
    "question",
    [
        "2주치 입금 건수는?",
        "직전 한 주에 입금은 몇 건이야?",
        "직전 24시간 동안 입금은 몇 건이야?",
        "24시간 동안 입금은 몇 건이야?",
    ],
)
def test_review2_week_and_hour_qualifiers_block(question: str) -> None:
    _blocked(question, IN_COUNT)


# ---------- medium 5 — 식별자 끝 숫자 · `이번 주요`(3회차에 막힘으로) ----------


def test_review2_ibeon_juyo_blocks_known_limit() -> None:
    """추가 검토 3 — `지난`/`이번`/`직전` + `주` 는 예외 없이 기간(원칙 (A)). 2회차엔 통과였으나 알고 남김(06 · 08)."""
    _blocked("입금 건수는?", "이번 주요 확인 항목은 {{period|과}} {{inbound.count|이에요}}.")


def test_review2_case_number_then_ju_georae_stays() -> None:
    question = "CASE-2022-000057 주 거래 계좌의 달러 입금 합계는?"
    assert _ask(question, "{{inbound.amount.USD|이}} 확인돼요.").status is AskStatus.ANSWERED


# ---------- medium 6 — 종결부호 상수 하나, 두 방향 ----------


@pytest.mark.parametrize("stop", STOPS)
def test_review2_stop_between_sentences_ends_p6(stop: str) -> None:
    _blocked("9/7 입금 건수는?", f"이 케이스는 {{{{period|예요}}}}{stop} 요청 날짜에 {IN_COUNT}")


@pytest.mark.parametrize("stop", STOPS)
def test_review2_stop_at_answer_end_stays(stop: str) -> None:
    answer = f"{{{{period}}}}에 {{{{inbound.count|이}}}} 확인돼요{stop}"
    assert _ask("입금 건수는?", answer).status is AskStatus.ANSWERED, stop
