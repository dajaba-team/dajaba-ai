"""기간 한정어 넓힘 — 숫자 날짜·상대 기간 질문에 기간 전체 집계가 통과하던 것(SCRUM-412, 9/7 점검, 정본 docs/str/06·08).

질문 쪽(`qualifier_mismatch`)과 절 쪽(`period_mismatch` P6 예외)은 같은 목록. 기존 목록에 덧붙이기만 — 막는 쪽으로만.
LLM 없음(가짜 LLM).
"""

from __future__ import annotations

import re
import unicodedata

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from aml_ai.str.domain import ask_checks, ask_qualifier
from aml_ai.str.domain.constants_ask_qualifier import RE_DATE_QUALIFIER
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
IN_COUNT = "{{inbound.count|이}} 확인돼요."
OUT_COUNT = "{{outbound.count|이}} 확인돼요."
P6_V6 = "질문하신 기간의 거래는 없어요. 이 케이스는 {{period|이며}}, {{inbound.count|이}} 확인돼요."
# SCRUM-412 전 목록(그대로 남아야 함 — 상위 집합)
_OLD = re.compile(
    r"\d+\s*(?:월|일|년)|\d+\s*시(?!간)|오전|오후|하루|당일|그날|주말|어제|오늘|지난달|이번\s*달"
)


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _hit(text: str) -> bool:
    return RE_DATE_QUALIFIER.search(unicodedata.normalize("NFKC", text)) is not None


def _ask(question: str, answer: str):  # noqa: ANN202
    llm = StubLlm([plan_text("FACT", None, ["flows"]), answer_text(True, answer)])
    svc, _ = build_service(llm, facts=MIXED)
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN"))


# ---------- 막힘 — 기간 전체 자리표를 고르면 MISMATCH ----------

BLOCKED = [
    ("2022-09-07 입금 몇 건이야?", IN_COUNT),
    ("2022.09.07 입금 건수", IN_COUNT),
    ("2022/09/07 입금 건수", IN_COUNT),
    ("9/7 출금 합계", OUT_COUNT),
    ("최근 일주일 동안 입금 상대 몇 개?", IN_COUNT),
    ("지난주 거래", IN_COUNT),
    ("이번 주 출금은?", OUT_COUNT),
    ("2주간 입금 건수", IN_COUNT),
    ("3개월 동안 입금", IN_COUNT),
    ("3달 동안 입금", IN_COUNT),
    ("한 달 동안 입금", IN_COUNT),
    ("한달 입금 합계", IN_COUNT),
    ("며칠 동안 들어왔어?", IN_COUNT),
    ("주간 입금 건수", IN_COUNT),
    ("작년 입금 건수", IN_COUNT),
    ("올해 출금 건수", OUT_COUNT),
    ("지난해 거래", IN_COUNT),
    ("금년 입금", IN_COUNT),
    ("전년 대비 입금", IN_COUNT),
    ("How many incoming transactions last week?", IN_COUNT),
    ("recent incoming count?", IN_COUNT),
    ("today incoming count?", IN_COUNT),
    ("3일간 출금", OUT_COUNT),  # SCRUM-412 전에도 막힘 — 회귀
    # 알고 남김 — 분수는 모두 날짜로 읽음(안전 쪽, 06 남는 위험 ⑥ · 08, 추가 검토 1·2)
    ("1/3 입금 건수", IN_COUNT),
    ("1/3 비율이야?", IN_COUNT),  # 추가 검토 2 — `비율` 예외도 없앰
    ("입금이 전체의 1/3 이상이야?", IN_COUNT),
    ("입금 중 1/3 정도가 현금이야?", IN_COUNT),
    ("입금의 1/3은 현금이야?", IN_COUNT),
]


@pytest.mark.parametrize(("question", "answer"), BLOCKED, ids=[q for q, _ in BLOCKED])
def test_period_qualifier_blocks_whole_period_slot(question: str, answer: str) -> None:
    res = _ask(question, answer)
    assert res.status is AskStatus.UNVERIFIED, question
    assert res.code_checks[0].draft_value == "질문 한정어와 다른 집계 1개"


# ---------- 통과 유지 — 한정어 아님, 기존 판정 그대로 ----------

KEPT = [
    ("입금 상대 계좌가 몇 개야?", IN_COUNT),
    ("전체 기간 입금 합계", IN_COUNT),
    ("기간 전체 출금 건수", OUT_COUNT),
    ("주요 상대 계좌", IN_COUNT),
    ("주로 어떤 결제 방식?", IN_COUNT),
    ("주 거래 상대는?", IN_COUNT),
    ("2 주요 상대", IN_COUNT),
    ("1,234.50 달러 입금 있어?", IN_COUNT),
    ("한달러 입금 있어?", IN_COUNT),
]


@pytest.mark.parametrize(("question", "answer"), KEPT, ids=[q for q, _ in KEPT])
def test_non_qualifier_questions_stay_answered(question: str, answer: str) -> None:
    assert _ask(question, answer).status is AskStatus.ANSWERED, question


# ---------- 정규식 경계 ----------


@pytest.mark.parametrize(
    "text",
    [
        "50달러",
        "100 달러 이상",
        "한 달러",
        "1,000달러",
        "12,345 건",
        "13/7 입금",
        "10_8000EBD30 계좌",
        "현금 거래",
        "CASE-2022-000031 입금 몇 건?",  # 다른 케이스 번호 질문은 계획 전 OUT_OF_SCOPE(06) — 정규식만 봄
    ],
)
def test_not_a_qualifier(text: str) -> None:
    assert not _hit(text), text


@pytest.mark.parametrize(
    "text",
    [
        "9월 7일",
        "3시",
        "오전",
        "오후",
        "하루",
        "당일",
        "그날",
        "주말",
        "어제",
        "오늘",
        "지난달",
        "이번 달",
        "2023년",
    ],
)
def test_old_list_still_matches(text: str) -> None:
    assert _OLD.search(text) and _hit(text), text


def test_question_and_clause_use_same_list() -> None:
    assert ask_checks.RE_DATE_QUALIFIER is RE_DATE_QUALIFIER
    assert ask_qualifier.RE_DATE_QUALIFIER is RE_DATE_QUALIFIER


# ---------- 절 쪽 — P6 예외 ----------


@pytest.mark.parametrize(
    "question", ["지난주에 들어온 거래는 몇 건이야?", "2022-09-07 에 들어온 거래는 몇 건이야?"]
)
def test_p6_shape_stays_answered_for_new_qualifiers(question: str) -> None:
    assert _ask(question, P6_V6).status is AskStatus.ANSWERED, question


@pytest.mark.parametrize("word", ["최근", "지난주"])
def test_clause_with_new_period_word_is_blocked(word: str) -> None:
    answer = f"이 케이스는 {{{{period|이며}}}}, {word} {IN_COUNT}"
    assert _ask("9월 3일에 들어온 거래는 몇 건이야?", answer).status is AskStatus.UNVERIFIED, answer
