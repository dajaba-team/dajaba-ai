"""기간 한정어 추가 검토 3 회귀 — 검토가 쓴 문장 그대로 (SCRUM-412, 정본 docs/str/06·08). LLM 없음(가짜 LLM).

P6 예외는 거래 기간에서 계산한 키에만 · 관측값 절의 기간 낱말은 자기 창 · `지난`/`이번`/`직전` + `주` 예외 없음 ·
`분`·숫자 범위 · `YY.MM.DD`·`M.D(요일)`.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
IN_COUNT = "{{inbound.count|이}} 확인돼요."
QUALIFIER = "질문 한정어와 다른 집계"


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _ask(question: str, answer: str, bundles: tuple[str, ...] = ("flows",)):  # noqa: ANN202
    llm = StubLlm([plan_text("FACT", None, list(bundles)), answer_text(True, answer)])
    svc, _ = build_service(llm, facts=MIXED)
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN"))


def _blocked(question: str, answer: str, bundles: tuple[str, ...] = ("flows",)) -> None:
    res = _ask(question, answer, bundles)
    assert res.status is AskStatus.UNVERIFIED, (question, answer)
    assert res.code_checks[0].draft_value.startswith(QUALIFIER)


# ---------- high 1 — P6 예외는 거래 기간에서 계산한 키에만 ----------


def test_review3_prior_alert_count_with_period_blocks() -> None:
    _blocked(
        "9/3에 이 계좌에서 발생한 과거 경보는 몇 건이야?",
        "{{period}}에 {{prior_alert_count|이}} 확인돼요.",
        ("subject", "flows"),
    )


# ---------- high 2 — 관측값 절의 기간 낱말은 자기 창 · 선언문은 막음 ----------


def test_review3_observation_window_word_stays() -> None:
    answer = (
        "하루 동안의 {{observations.account_in_counterparties_24h|이}} 확인돼요. "
        "케이스 전체에서 {{inbound.count|이}} 확인돼요."
    )
    res = _ask("이 케이스의 관측 지표와 입금 건수는?", answer, ("observations", "flows"))
    assert res.status is AskStatus.ANSWERED


def test_review3_declared_period_sentence_still_blocks() -> None:
    _blocked("입금 건수는?", "지난주 기준이에요. {{inbound.count|이}} 확인돼요.")


# ---------- high 3·4·5 — 질문 쪽 ----------


@pytest.mark.parametrize(
    "question",
    [
        "조회 기간은 지난주요. 입금은 몇 건이야?",
        "지난주거래 중 입금은 몇 건이야?",
        "마지막 거래 직전 30분 동안 입금은 몇 건이야?",
        "마지막 거래 전 1-2시간 사이에 입금은 몇 건이야?",
        "마지막 거래 전 1~2시간 사이에 입금은 몇 건이야?",
        "9.7(수) 입금은 몇 건이야?",
        "22.09.07 입금은 몇 건이야?",
    ],
)
def test_review3_question_qualifiers_block(question: str) -> None:
    _blocked(question, IN_COUNT)


@pytest.mark.parametrize(
    "question",
    [
        "이번 해외송금 점검용으로 이 계좌의 전체 입금 건수를 알려줘",
        "1,234.50 달러 입금 있어?",
        "9.75 달러 입금 있어?",
    ],
)
def test_review3_non_qualifiers_stay(question: str) -> None:
    assert _ask(question, IN_COUNT).status is AskStatus.ANSWERED, question
