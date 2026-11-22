"""질문 답변 고치기 — 금액 정확 값 · 추가 검토 1 회귀: 방향 근거 키(H2) · 금액 관측값(M2) (SCRUM-358·359, 정본 docs/str/06 8·9번).

녹화 없이 가짜 LLM·픽스처 facts 로만. test_ask_direction_fix 에서 나눔(200줄 관문).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from aml_ai.str.domain import ask_checks
from aml_ai.str.domain.models import Transaction
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text

S = "10_8000EBD30"


def _mixed() -> Facts:
    return Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))


def _tx(i: int, src: str, dst: str) -> Transaction:
    one = Decimal("1.00")
    return Transaction(i, datetime(2022, 9, 3), src, dst, one, "USD", one, "USD", "ACH", False)


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


# ---------- 추가 검토 1 H2 · 2 H4 — 방향 근거 키 ----------


def _ask_mixed(answer: str, cites: list[str]):
    llm = StubLlm(
        responses=[plan_text("FACT", None, ["counterparties"]), answer_text(answer=answer, cites=cites)]
    )
    svc, _ = build_service(llm, facts=_mixed())
    return svc.ask(ask_request("입금 상대 계좌는 몇 개야?", rule_id="R02_FAN_IN"))


def test_direction_answer_citing_other_side_is_unverified() -> None:
    """검토 1 재현 — 입금 2 답에 출금 키만 인용하면 전엔 ANSWERED·근거 [3,4,5]. 이제 그 숫자 COUNT 줄이 MISSING → UNVERIFIED."""
    res = _ask_mixed("입금 상대는 2개예요.", ["counterparties_by_direction.outbound.count"])
    assert res.status is AskStatus.UNVERIFIED and res.evidence_ids == []
    (row,) = [c for c in res.code_checks if c.check.value == "COUNT_MATCH"]
    assert (row.match, row.reason.value) == (False, "MISSING")


def test_direction_answer_with_same_side_key_evidence_only_that_side() -> None:
    res = _ask_mixed("입금 상대는 2개예요.", ["counterparties_by_direction.inbound.count"])
    assert res.status is AskStatus.ANSWERED and res.evidence_ids == [1, 2]


@pytest.mark.parametrize("extra", ["counterparties_by_direction.outbound.count", "counterparties.count"])
def test_unused_counterparty_key_dropped_from_evidence(extra: str) -> None:
    """검토 2 재현 — 입금 2 답에 안 쓰인 상대 키를 덧붙이면 ANSWERED 이되 근거는 입금 거래만(실패 사유 아님)."""
    res = _ask_mixed("입금 상대는 2개예요.", ["counterparties_by_direction.inbound.count", extra])
    assert res.status is AskStatus.ANSWERED and res.evidence_ids == [1, 2]


def test_undirected_answer_to_directed_question_is_unverified() -> None:
    """검토 3 H4 재현 — `입금 상대 계좌는 몇 개야?` 에 방향 없이 `상대 계좌는 모두 4개` + 전체 키 → 전엔 ANSWERED·근거 [1..5].
    이제 질문 방향(입금)과 대조 → 입금 상대 2 ≠ 4 → UNVERIFIED."""
    res = _ask_mixed("상대 계좌는 모두 4개예요.", ["counterparties.count"])
    assert (res.status, res.answer, res.evidence_ids) == (AskStatus.UNVERIFIED, None, [])


def test_undirected_answer_to_undirected_question_keeps_total_key() -> None:
    """방향 없는 질문이면 방향 없는 상대 수(전체 4)는 counterparties.count 인용으로 ANSWERED."""
    llm = StubLlm(
        responses=[
            plan_text("FACT", None, ["counterparties"]),
            answer_text(answer="상대 계좌는 모두 4개예요.", cites=["counterparties.count"]),
        ]
    )
    svc, _ = build_service(llm, facts=_mixed())
    res = svc.ask(ask_request("상대 계좌는 몇 개야?", rule_id="R02_FAN_IN"))
    assert res.status is AskStatus.ANSWERED and res.evidence_ids == [1, 2, 3, 4, 5]


# ---------- 추가 검토 1 M2 — 금액 관측값 ----------


def _facts_with_eur_obs() -> Facts:
    """mixed + 금액 관측값(unit amount · basis sum_inbound_amount_eur 18000.0) + EUR 범위(공용 검사는 통과하는 값)."""
    d = load_json(FIXTURES / "facts_ask_mixed.json")
    d["observations"] = [
        {"name": "cross_border_amount_24h", "value": 18000.0, "unit": "amount", "window_start": "2022-09-03T00:00:00",
         "window_end": "2022-09-04T00:00:00", "basis": "sum_inbound_amount_eur", "baseline": None}
    ]  # fmt: skip
    d["amount_range"] = [*d["amount_range"], {"currency": "EUR", "min": "9000.00", "max": "20000.00"}]
    return Facts.model_validate(d)


@pytest.mark.parametrize(
    ("cites", "match"),
    [(["observations.cross_border_amount_24h"], True), (["amount_range.USD.max"], False)],
    ids=["관측 키 인용 → 정확 값 허용", "관측 키 안 인용 → 범위 안이어도 MISMATCH"],
)
def test_amount_observation_exact_when_cited(cites: list[str], match: bool) -> None:
    rows = [
        c
        for c in ask_checks.run(_facts_with_eur_obs(), "관측값은 18000.0 EUR 예요.", cites, cites)
        if c.check.value == "AMOUNT_MATCH"
    ]
    assert len(rows) == 1 and rows[0].match is match


# ---------- 금액 정확 값 ----------


@pytest.mark.parametrize(
    ("answer", "cites", "match"),
    [
        ("가장 큰 금액은 15000.00 USD 예요.", ["amount_range.USD.max"], True),  # 최대 표시 = max 키
        ("입금 합계는 27250.50 USD 예요.", ["inbound.amount.USD"], True),  # 합계 + 입금 = 입금 합계 키
        ("가장 작은 금액은 7000.00 USD 예요.", ["amount_range.USD.min"], True),
        (
            "한 상대에게 14000.00 USD 를 보냈어요.",
            ["amount_range.USD.max"],
            False,
        ),  # 개별 대상 — facts 에 개별 금액 없음
        ("가장 큰 금액은 15000.00 USD 예요.", ["amount_range.USD.min"], False),  # 종류와 다른 키
        ("입금 합계는 27250.50 USD 예요.", ["outbound.amount.USD"], False),  # 방향과 다른 키
    ],
)
def test_ask_amount_kind_and_key(answer: str, cites: list[str], match: bool) -> None:
    """금액 종류 표시 = 인용 키 종류 + 방향(06 질문 답변 8번, 추가 검토 3) — 예문의 인용 키를 종류에 맞춤."""
    rows = [c for c in ask_checks.run(_mixed(), answer, cites, cites) if c.check.value == "AMOUNT_MATCH"]
    assert len(rows) == 1 and rows[0].match is match


def test_shared_amount_match_still_range() -> None:
    """초안·요약 공용 검사는 그대로 — 범위 안 금액 match(06 한계 표 2번)."""
    from aml_ai.str.domain.verification import run_summary_code_checks

    rows = [
        c
        for c in run_summary_code_checks(_mixed(), ["한 건은 14000.00 USD 예요."], [])
        if c.check.value == "AMOUNT_MATCH"
    ]
    assert len(rows) == 1 and rows[0].match


# ---------- 추가 검토 2 H1·M1 — 관측값 금액은 관측 설명 문장에서만 ----------


def _facts_eur(*, usd_only: bool) -> Facts:
    """관측값 14000.0 EUR(unit amount · basis sum_inbound_amount_eur). usd_only 면 거래에 EUR 없음."""
    d = load_json(FIXTURES / "facts_ask_mixed.json")
    d["observations"] = [
        {"name": "cross_border_amount_24h", "value": 14000.0, "unit": "amount", "window_start": "2022-09-03T00:00:00",
         "window_end": "2022-09-04T00:00:00", "basis": "sum_inbound_amount_eur", "baseline": None}
    ]  # fmt: skip
    if not usd_only:
        d["amount_range"] = [*d["amount_range"], {"currency": "EUR", "min": "7000.00", "max": "20000.00"}]
    return Facts.model_validate(d)


def _amount_row(facts: Facts, answer: str, cites: list[str]):
    (row,) = [c for c in ask_checks.run(facts, answer, cites, cites) if c.check.value == "AMOUNT_MATCH"]
    return row


def test_observation_amount_not_allowed_in_transfer_sentence() -> None:
    """검토 2 재현 — 관측 키를 인용해도 `한 상대에게 14000.00 EUR 를 보냈어요` 는 관측 설명 문장이 아님 → MISMATCH."""
    row = _amount_row(
        _facts_eur(usd_only=False),
        "한 상대에게 14000.00 EUR 를 보냈어요.",
        ["observations.cross_border_amount_24h"],
    )
    assert row.match is False


def test_observation_amount_judged_by_cited_observation_even_without_currency_in_flows() -> None:
    """검토 2 재현 — USD 거래만 + 관측 설명 문장 `관측값은 14000.00 EUR 예요` → 관측 키 값·통화로 직접 match, 출처에 관측 키."""
    row = _amount_row(
        _facts_eur(usd_only=True), "관측값은 14000.00 EUR 예요.", ["observations.cross_border_amount_24h"]
    )
    assert row.match is True and row.source_value.startswith("observations.cross_border_amount_24h")
