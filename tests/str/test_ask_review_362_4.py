"""추가 검토 4(SCRUM-362 ★B8) 반례 — 고치기 전에 넣어 실패를 확인 (정본 docs/str/04 "집계 값의 범위 표시" · 06).

N-1 근거 범위(일부·모름) · N-2 대외 범위(내부 섞임) · D-1 날짜 + 최대·최소 · D-2 자리표 출현별 기간 · 판정 도구 `며,` 경계 ·
평가 픽스처 범위 계산. LLM 없음(가짜 LLM).
"""

from __future__ import annotations

import pytest
from tools import ask_judge_text
from tools.ask_fixture_scope import fixture_scope

from aml_ai.shared.schemas.str import AskStatus, Facts
from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.domain.ask_scope import AskScope
from aml_ai.str.domain.ask_slots import render
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text
from tests.str.facts_support import CASES, build

LABELS = load_display_labels()
S = CASES["subject"]["account_key"]
MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
MULTI = Facts.model_validate(load_json(FIXTURES / "facts_multi_currency.json"))
FAN_IN = Facts.model_validate(load_json(FIXTURES / "facts_ask_fan_in.json"))
WHOLE = AskScope(whole_alert=True, ownership_known=True)
SUBSET = AskScope(whole_alert=False, ownership_known=True)


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _row(k: int, src: str, dst: str, fmt: str = "ACH") -> dict:
    return {
        "transaction_id": k,
        "ts": f"2022-09-02T{10 + k:02d}:00:00",
        "from_account_key": src,
        "to_account_key": dst,
        "amount_paid": "100.00",
        "currency_paid": "USD",
        "amount_received": "100.00",
        "currency_received": "USD",
        "payment_format": fmt,
        "is_self_transfer": False,
    }


def _text(facts: Facts, answer: str, scope: AskScope | None, bundles: tuple[str, ...] = ("flows",)) -> str:
    return render(answer, extract(facts, "R02_FAN_IN", list(bundles), LABELS, scope=scope), LABELS).text


def _status(question: str, answer: str, facts: Facts, bundles: tuple[str, ...] = ("flows",)) -> AskStatus:
    llm = StubLlm([plan_text("FACT", None, list(bundles)), answer_text(True, answer)])
    svc, _ = build_service(llm, facts=facts)
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN")).status


# ---------- N-1 근거 범위 — 일부·모름이면 값 끝에 (근거 거래 기준) ----------


@pytest.mark.parametrize("scope", [SUBSET, None], ids=["subset", "unknown"])
def test_partial_or_unknown_evidence_marks_zero_count_and_formats(scope: AskScope | None) -> None:
    assert (
        _text(FAN_IN, "{{outbound.count|이}} 확인돼요.", scope)
        == "출금 거래 0건 (근거 거래 기준)이 확인돼요."
    )
    assert (
        _text(FAN_IN, "{{payment_formats|이에요}}.", scope, ("formats",))
        == "결제 방식 ACH (근거 거래 · 대외 거래 기준)이에요."
    )
    assert _text(FAN_IN, "{{period|이에요}}.", scope).endswith("(근거 거래 기준)이에요.")


def test_whole_alert_evidence_has_no_evidence_mark() -> None:
    assert _text(FAN_IN, "{{outbound.count|이}} 확인돼요.", WHOLE) == "출금 거래 0건이 확인돼요."


# ---------- N-2 대외 범위 — 내부·간접 거래가 있으면 대외만 센 값에 (대외 거래 기준) ----------

WITH_INTERNAL = build({"transactions": [_row(1, "020_A0000001", S), _row(2, "10_S0000002", S)]})


@pytest.mark.parametrize(
    ("answer", "want"),
    [
        ("{{inbound.count|이에요}}", "입금 거래 1건 (대외 거래 기준)이에요"),
        ("{{counterparties.count|이에요}}", "입출금 전체 상대 계좌 1개 (대외 거래 기준)이에요"),
        ("{{amount_range.USD.max|이에요}}", "(대외 거래 기준)이에요"),
    ],
)
def test_internal_mixed_marks_external_only_values(answer: str, want: str) -> None:
    assert WITH_INTERNAL.internal.count == 1
    text = _text(WITH_INTERNAL, answer, WHOLE, ("flows", "counterparties"))
    assert text.endswith(want), text


def test_no_internal_has_no_external_mark() -> None:
    assert _text(FAN_IN, "{{inbound.count|이에요}}", WHOLE) == "입금 거래 3건이에요"


# ---------- 평가 픽스처 범위 — 서비스와 같은 ask_scope 로 계산 ----------


def test_fixture_scope_is_computed_from_request_and_fixture() -> None:
    req = ask_request("입금 거래는 몇 건이야?", rule_id="R02_FAN_IN")
    assert fixture_scope(FAN_IN, req) == AskScope(whole_alert=True, ownership_known=False)


def test_build_service_uses_fixture_scope_by_default_and_unknown_on_request() -> None:
    llm = StubLlm([plan_text("FACT", None, ["flows"]), answer_text(True, "{{outbound.count|이}} 확인돼요.")])
    svc, _ = build_service(llm, facts=FAN_IN)
    assert svc.ask(ask_request("출금 거래는?", rule_id="R02_FAN_IN")).answer == "출금 거래 0건이 확인돼요."
    llm = StubLlm([plan_text("FACT", None, ["flows"]), answer_text(True, "{{outbound.count|이}} 확인돼요.")])
    svc, _ = build_service(llm, facts=FAN_IN, scope=None)
    assert svc.ask(ask_request("출금 거래는?", rule_id="R02_FAN_IN")).answer.endswith(
        "(근거 거래 기준)이 확인돼요."
    )


# ---------- D-1 날짜 + 최대·최소 — 따로 세서 더함 ----------


def test_date_and_extreme_qualifier_still_checks_totals() -> None:
    answer = "{{period}}에 {{outbound.amount.USD|이}} 확인돼요."
    assert _status("9월 3일 최대 출금액은 얼마야?", answer, MIXED) is AskStatus.UNVERIFIED


# ---------- D-2 기간 예외는 자리표 출현마다 · 며, 경계 ----------


@pytest.mark.parametrize(
    "answer",
    [
        "{{period}}에 {{inbound.count|이}} 확인돼요. 그날도 {{inbound.count|이}} 확인돼요.",
        "전체 기간은 {{period|이며}}, 그날은 {{inbound.count|이}} 확인돼요.",
    ],
)
def test_period_exception_is_per_occurrence(answer: str) -> None:
    assert _status("9월 3일에 들어온 거래는 몇 건이야?", answer, MULTI) is AskStatus.UNVERIFIED, answer


@pytest.mark.parametrize(
    "answer",
    [
        "질문하신 기간의 거래는 없어요. 이 케이스에는 {{period}}에 {{inbound.count|이}} 확인돼요.",  # P6 v5
        "질문하신 기간의 거래는 없어요. 이 케이스는 {{period|이며}}, {{inbound.count|이}} 확인돼요.",  # P6 v6
    ],
)
def test_p6_shapes_stay_answered(answer: str) -> None:
    assert _status("2023년 1월에 들어온 거래는 몇 건이야?", answer, FAN_IN) is AskStatus.ANSWERED, answer


# ---------- 판정 도구 — 자리표 안 조사 `이며` 뒤 쉼표도 절 경계 ----------


def test_judge_clause_breaks_after_imyeo_particle() -> None:
    piece = extract(MIXED, "R02_FAN_IN", ["flows"], LABELS, scope=WHOLE)
    raw = "{{outbound.count|이며}}, 입금은 확인되지 않아요."  # 같은 절이면 출금 키 + 입금 낱말 = 어긋남으로 오판
    assert ask_judge_text.slot_direction_conflicts(raw, piece) == 0
