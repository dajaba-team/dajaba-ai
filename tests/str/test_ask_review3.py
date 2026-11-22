"""질문 답변 추가 검토 3 재현 — AskService 응답 상태·공개 본문·근거 ID (SCRUM-358·359, 정본 docs/str/06 "질문 답변" 8·10번).

원칙: 판정 못 하면 통과 안 시킴. 검토 3 이 ANSWERED 로 재현한 오답은 전부 UNVERIFIED(본문 null · 근거 []).
맞는 모양(종류 표시가 분명한 답)은 ANSWERED 로 남는지 대조 사례를 같이 둔다. 가짜 LLM — 녹화 아님.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

OBS = "observations.cross_border_amount_24h"


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _mixed(*, eur_obs: bool = False, usd_only: bool = True) -> Facts:
    """입금 2(USD 27250.50) · 출금 3(USD 24500.25) · 상대 입금 2·출금 3·전체 4(전부 타행) [+ 관측 14000.0 EUR]."""
    d = load_json(FIXTURES / "facts_ask_mixed.json")
    if eur_obs:
        d["observations"] = [
            {"name": "cross_border_amount_24h", "value": 14000.0, "unit": "amount", "window_start": "2022-09-03T00:00:00",
             "window_end": "2022-09-04T00:00:00", "basis": "sum_inbound_amount_eur", "baseline": None}
        ]  # fmt: skip
    if not usd_only:
        d["amount_range"] = [*d["amount_range"], {"currency": "EUR", "min": "7000.00", "max": "20000.00"}]
    return Facts.model_validate(d)


def _ask(facts: Facts, question: str, answer: str, cites: list[str], bundles: list[str] | None = None):
    llm = StubLlm(responses=[plan_text("FACT", None, bundles or ["flows", "counterparties", "observations"]),
                             answer_text(answer=answer, cites=cites)])  # fmt: skip
    svc, _ = build_service(llm, facts=facts)
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN"))


def _unverified(res) -> None:  # noqa: ANN001
    assert (res.status, res.answer, res.cites, res.evidence_ids) == (AskStatus.UNVERIFIED, None, [], [])


# ---------- 금액 (H1·H2·H3) ----------


def test_h1_other_currency_observation_does_not_pass_transfer_amount() -> None:
    res = _ask(_mixed(eur_obs=True, usd_only=False), "금액 알려 줘",
               "관측값은 14000.00 EUR예요. 한 상대에게 약 999999 USD를 보냈어요.", [OBS])  # fmt: skip
    _unverified(res)


def test_h2_word_observation_alone_does_not_allow_transfer() -> None:
    res = _ask(_mixed(eur_obs=True), "관측 결과는?", "관측 결과 한 상대에게 14000.00 EUR를 보냈어요.", [OBS])
    _unverified(res)


def test_h3_total_is_not_a_single_counterparty_amount() -> None:
    res = _ask(_mixed(), "보낸 돈은?", "한 상대에게 24500.25 USD를 보냈어요.", ["outbound.amount.USD"])
    _unverified(res)


def test_observation_amount_said_directly_passes() -> None:
    res = _ask(_mixed(eur_obs=True), "관측값은?", "관측값은 14000.00 EUR예요.", [OBS])
    assert res.status is AskStatus.ANSWERED


@pytest.mark.parametrize(
    ("answer", "cites", "status"),
    [
        ("입금액은 27250.50 USD예요.", ["inbound.amount.USD"], AskStatus.ANSWERED),  # 358 P5 모양 — 방향이 바로 꾸밈
        ("입금이 27250.50 USD, 출금이 24500.25 USD예요.", ["inbound.amount.USD", "outbound.amount.USD"], AskStatus.ANSWERED),
        ("입금액은 27250.50 USD예요.", ["outbound.amount.USD"], AskStatus.UNVERIFIED),  # 방향과 다른 키
        ("USD의 최대와 최소는 모두 15000.00 USD예요.", ["amount_range.USD.max", "amount_range.USD.min"], AskStatus.UNVERIFIED),
    ],
)  # fmt: skip
def test_amount_marks_added_in_review3_stop_answer(answer: str, cites: list[str], status: AskStatus) -> None:
    """검토 3 멈춤 답 (b) ② 방향이 바로 꾸밈 · ① `최대와 최소는 모두 X` 는 X 가 max·min 둘 다일 때만(여기선 다름)."""
    assert _ask(_mixed(), "금액은?", answer, cites).status is status


def test_both_extremes_all_passes_when_equal() -> None:
    """18 F8 모양 — EUR 가 한 건이라 max = min = 9800.25, 두 키 다 인용."""
    facts = Facts.model_validate(load_json(FIXTURES / "facts_multi_currency.json"))
    res = _ask(facts, "가장 큰 입금액과 가장 작은 입금액은?", "EUR의 최대와 최소는 모두 9800.25 EUR로 보여요.",
               ["amount_range.EUR.max", "amount_range.EUR.min"], ["flows"])  # fmt: skip
    assert res.status is AskStatus.ANSWERED


# ---------- 상대 수 (H4·H5·H6) ----------


def test_h4_directed_question_rejects_total() -> None:
    _unverified(
        _ask(_mixed(), "입금 상대 계좌는 몇 개야?", "상대 계좌는 모두 4개예요.", ["counterparties.count"])
    )


@pytest.mark.parametrize(
    "answer",
    [
        "전체 상대 중에서 입금 상대는 계좌 4개예요.",
        "4명의 서로 다른 수취인에게 보냈어요.",
        "4개 계좌가 보낸 돈이 입금됐어요.",
    ],
)
def test_h5_missed_modifier_never_falls_back_to_total(answer: str) -> None:
    _unverified(_ask(_mixed(), "상대 계좌는 몇 개야?", answer, ["counterparties.count"]))


def test_h6_subset_inherits_latest_total_scope() -> None:
    """`이 가운데` 는 바로 앞 주장(전체 4)의 범위 — 전체 타행 4 ≠ 2 → UNVERIFIED (전엔 입금 범위를 물려 받아 통과)."""
    answer = "입금 상대는 2개예요. 전체 상대 계좌는 4개예요. 이 가운데 타행 계좌는 2개예요."
    cites = [
        "counterparties_by_direction.inbound.count",
        "counterparties.count",
        "counterparty_banks.other_bank_accounts",
    ]
    _unverified(_ask(_mixed(), "상대 계좌는 몇 개야?", answer, cites))


def test_h6_subset_of_total_with_right_value_passes() -> None:
    answer = "전체 상대 계좌는 4개예요. 이 가운데 타행 계좌는 4개예요."
    res = _ask(
        _mixed(),
        "상대 계좌는 몇 개야?",
        answer,
        ["counterparties.count", "counterparty_banks.other_bank_accounts"],
    )
    assert res.status is AskStatus.ANSWERED and res.evidence_ids == [1, 2, 3, 4, 5]
