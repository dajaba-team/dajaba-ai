"""추가 검토 1~4(SCRUM-358·359) 재현 세트를 자리표 구조로 (SCRUM-362, 정본 docs/str/08 "자리표 다시 재기"). 가짜 LLM.

(가) 재현 오답 문장 **원문 그대로**를 v3 답으로 → 전부 ANSWERED 아님(목표 0).
(나) 같은 오답을 **자리표로 바꾼 꼴**(그 오답에 가장 가까운 틀린 키) → 막힘(어느 표시) / 남음(06 남는 위험 ①·②) 표.
facts 는 `facts_ask_mixed`(입금 2·출금 3·상대 전체 4·입금 상대 2·출금 상대 3, USD 만) — 원문 재현의 관측값 픽스처 대신
같은 문장 꼴을 이 케이스에 둠(원문은 숫자가 자리표 밖이라 facts 와 상관없이 막힘).
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from tests.conftest import EXAMPLES, FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

CASE = load_json(EXAMPLES / "ask_request.json")["case_no"]
OTHER = "CASE-2022-000058" if CASE != "CASE-2022-000058" else "CASE-2022-000059"
PLAN = plan_text("FACT", None, ["flows", "counterparties", "observations"])
Q_IN = "입금 상대 계좌는 몇 개야?"
Q_ALL = "입출금 상대 계좌는 모두 몇 개야?"
Q_AMT = "돈은 얼마나 오갔어?"
OBS = "{{observations.account_in_counterparties_24h|이}}"


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _ask(question: str, answer: str):
    llm = StubLlm(responses=[PLAN, answer_text(answer=answer)])
    facts = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
    svc, repo = build_service(llm, facts=facts)
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN")), llm, repo


# ---------- (가) 원문 그대로 ----------

ORIGINAL = [
    ("r1-h1a", Q_ALL, "입출금 전체의 상대 계좌는 3개예요."),
    ("r1-h1b", Q_ALL, "수취인은 모두 3명이며 받은 금액은 서로 달라요."),
    ("r1-h2", Q_IN, "입금 상대는 2개예요."),
    ("r2-h1", Q_AMT, "한 상대에게 14000.00 EUR를 보냈어요."),
    ("r2-h2", Q_IN, "전체 상대 중 입금 상대는 계좌 4개예요."),
    ("r2-h3", Q_ALL, "수취인 계좌는 모두 2개이며 받은 금액은 서로 달라요."),
    ("r2-h4", Q_ALL, "전체 상대는 계좌 4개예요. 입금 상대는 계좌 2개예요."),
    ("r3-h1", Q_AMT, "관측값은 14000.00 EUR예요. 한 상대에게 약 999999 USD를 보냈어요."),
    ("r3-h2", Q_AMT, "관측 결과 한 상대에게 14000.00 EUR를 보냈어요."),
    ("r3-h3", Q_AMT, "한 상대에게 24500.25 USD를 보냈어요."),
    ("r3-h4", Q_IN, "상대 계좌는 모두 4개예요."),
    ("r3-h5a", Q_IN, "전체 상대 중에서 입금 상대는 계좌 4개예요."),
    ("r3-h5b", Q_ALL, "4명의 서로 다른 수취인에게 보냈어요."),
    ("r3-h5c", Q_ALL, "4개 계좌가 보낸 돈이 입금됐어요."),
    ("r3-h6", Q_ALL, "입금 상대는 2개예요. 전체 상대 계좌는 4개예요. 이 가운데 타행 계좌는 2개예요."),
    ("r3-m1", Q_IN, "입금 상대는 계좌 2개예요."),
    ("r4-h1a", Q_AMT, "가장 큰 출금액은 24500.25 USD예요."),
    ("r4-h1b", Q_AMT, "출금의 최대와 최소는 모두 9800.25 EUR예요."),
    ("r4-h2", Q_AMT, "입금 합계는 27250.50 USD예요. 27250.50 USD를 한 번에 받았어요."),
    ("r4-h3a", Q_AMT, "지표를 보면 14000.00 EUR가 출금됐어요."),
    ("r4-h3b", Q_AMT, "출금 관측값은 14000.00 EUR예요."),
    ("r4-h4", Q_IN, "출금 상대는 계좌 3개예요."),
    ("r4-h5a", Q_IN, "입금 상대 계좌는 전체 4개예요."),
    ("r4-h5b", Q_ALL, "상대 계좌는 3개예요."),
    ("r4-h6", "입금 합계는?", f"{OTHER}의 입금 합계는 27250.50 USD예요."),
]


@pytest.mark.parametrize(("rid", "question", "answer"), ORIGINAL, ids=[r[0] for r in ORIGINAL])
def test_original_wrong_answer_is_never_answered(rid: str, question: str, answer: str) -> None:
    res, _, repo = _ask(question, answer)
    assert res.status is AskStatus.UNVERIFIED, rid
    assert (res.answer, res.cites, res.evidence_ids) == (None, [], [])
    assert answer not in res.model_dump_json()
    assert repo.saved[0]["response_payload"]["llm_answer"]["answer"] == answer


# ---------- (나) 자리표로 바꾼 꼴 ----------

BLOCKED, REMAINS_KEY, REMAINS_PROSE = "막힘", "남음 ① 다른 키", "남음 ② 둘레 문장"
CB = "counterparties_by_direction"
SLOTTED = [
    (
        "r1-h1a",
        Q_ALL,
        "입출금 전체의 상대 계좌는 {{" + CB + ".outbound.count|이에요}}.",
        BLOCKED,
        "반대 방향 키만 1개",
    ),  # 추가 검토 2 — 양방향 질문 한쪽만
    (
        "r1-h1b",
        Q_ALL,
        "수취인은 모두 {{" + CB + ".inbound.count|이에요}}.",
        BLOCKED,
        "반대 방향 키만 1개",
    ),  # 추가 검토 2 — 양방향 질문 한쪽만
    ("r1-h2", Q_IN, "입금 상대는 {{" + CB + ".outbound.count|이에요}}.", BLOCKED, "반대 방향 키만 1개"),
    (
        "r2-h1",
        Q_AMT,
        "한 상대에게 {{outbound.amount.USD|을}} 보냈어요.",
        BLOCKED,
        "자리표 밖 서술어 1개",
    ),  # 추가 검토 3 허용 목록으로 닫힘
    ("r2-h2", Q_IN, "전체 상대 중 입금 상대는 {{counterparties.count|이에요}}.", REMAINS_KEY, None),
    (
        "r3-h3",
        Q_AMT,
        "한 상대에게 {{outbound.amount.USD|을}} 보냈어요.",
        BLOCKED,
        "자리표 밖 서술어 1개",
    ),  # 추가 검토 3 허용 목록으로 닫힘
    ("r3-h4", Q_IN, "{{counterparties.count|이에요}}.", REMAINS_KEY, None),
    (
        "r3-h5b",
        Q_ALL,
        "{{counterparties.count|과}} 서로 다른 수취인에게 보냈어요.",
        BLOCKED,
        "자리표 밖 서술어 1개",
    ),  # 추가 검토 3 허용 목록으로 닫힘
    (
        "r3-h6",
        Q_ALL,
        "이 가운데 {{" + CB + ".inbound.other_bank_accounts|이에요}}.",
        BLOCKED,
        "반대 방향 키만 1개",
    ),  # 추가 검토 2 — 양방향 질문 한쪽만
    ("r4-h1a", Q_AMT, "가장 큰 출금액은 {{outbound.amount.USD|이에요}}.", REMAINS_PROSE, None),
    ("r4-h2", Q_AMT, "{{inbound.amount.USD|을}} 한 번에 받았어요.", BLOCKED, "자리표 밖 숫자 1개"),
    (
        "r4-h3a",
        Q_AMT,
        f"지표를 보면 {OBS} 출금됐어요.",
        BLOCKED,
        "자리표 밖 서술어 1개",
    ),  # 추가 검토 3 허용 목록으로 닫힘
    ("r4-h4", Q_IN, "{{" + CB + ".outbound.count|이에요}}.", BLOCKED, "반대 방향 키만 1개"),
    ("r4-h5a", Q_IN, "입금 상대 계좌는 {{counterparties.count|이에요}}.", REMAINS_KEY, None),
    (
        "r4-h5b",
        Q_ALL,
        "{{" + CB + ".outbound.count|이에요}}.",
        BLOCKED,
        "반대 방향 키만 1개",
    ),  # 추가 검토 2 — 양방향 질문 한쪽만
    (
        "r4-h6",
        "입금 합계는?",
        f"{OTHER}의 {{{{inbound.amount.USD|이에요}}}}.",
        BLOCKED,
        "다른 케이스 번호 1개",
    ),
]


@pytest.mark.parametrize(("rid", "question", "answer", "kind", "mark"), SLOTTED, ids=[r[0] for r in SLOTTED])
def test_slotted_wrong_answer_blocked_or_known_remaining(
    rid: str, question: str, answer: str, kind: str, mark: str | None
) -> None:
    """남음은 ANSWERED 지만 값은 그 키의 이름표와 함께 나가 숫자 자체는 참(06 남는 위험 ①·②)."""
    res, _, _ = _ask(question, answer)
    if kind == BLOCKED:
        assert res.status is AskStatus.UNVERIFIED and res.code_checks[0].draft_value == mark, rid
        return
    assert res.status is AskStatus.ANSWERED, rid
    assert "{{" not in res.answer and res.cites


# ---------- H6 다른 케이스 (추가 검토 4 — 그대로) ----------


def test_h6_question_naming_other_case_ends_before_plan() -> None:
    llm = StubLlm(responses=[])  # 부르면 IndexError
    svc, repo = build_service(llm, facts=Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json")))
    res = svc.ask(ask_request(f"{OTHER}의 입금 합계는?", rule_id="R02_FAN_IN"))
    assert (res.status, res.out_of_scope_reason.value, res.evidence_ids) == (
        AskStatus.OUT_OF_SCOPE,
        "OUTSIDE_CASE",
        [],
    )
    assert llm.calls == [] and repo.saved[0]["response_payload"]["plan"]["source"] == "code"


def test_h6_question_naming_own_case_goes_to_plan() -> None:
    res, llm, _ = _ask(f"{CASE}의 입금 합계는?", "{{inbound.amount.USD|이에요}}")
    assert res.status is AskStatus.ANSWERED and len(llm.calls) == 2
    assert res.answer == "입금 합계 27,250.50 USD예요" and res.evidence_ids == [1, 2]
