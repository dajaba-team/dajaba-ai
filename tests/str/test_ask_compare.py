"""(B1) 비교는 코드 자리표로 — compare·vs_baseline 렌더링 · 자리표 밖 비교 꼴 차단 · 판정 도구 비교 판정 (SCRUM-362, 정본 04·06·08).

고치기 전에 넣어 실패를 확인한 반례. LLM 없음(가짜 LLM).
"""

from __future__ import annotations

import pytest
from tools import ask_judge_text
from tools import ask_premise_judge as judge

from aml_ai.shared.schemas.str import AskStatus, Facts
from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.domain.ask_checks import run
from aml_ai.str.domain.ask_scope import AskScope
from aml_ai.str.domain.ask_slots import render
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json
from tests.str.ask_recorded_support import FixedAnswer, facts_for, recorded
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text
from tests.str.facts_support import CASES, build

LABELS = load_display_labels()
WHOLE = AskScope(
    whole_alert=True, ownership_known=True
)  # 범위 표시가 아닌 렌더링 시험 — 근거 = 경보 전체(★B8)
S = CASES["subject"]["account_key"]
MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))
MULTI = Facts.model_validate(load_json(FIXTURES / "facts_multi_currency.json"))
PATHS = Facts.model_validate(load_json(FIXTURES / "facts_ask_paths.json"))
GAPS = {i["id"]: i for i in load_json(judge.GAPS_SET)["items"]}


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _text(facts: Facts, bundles: list[str], answer: str, rule: str = "R02_FAN_IN") -> str:
    return render(answer, extract(facts, rule, bundles, LABELS, scope=WHOLE), LABELS).text


# ---------- 렌더링 ----------


def test_compare_count_and_amount_are_code_rendered() -> None:
    assert (
        _text(MIXED, ["flows"], "{{compare.count}}") == "거래 건수 비교 입금 2건, 출금 3건 · 출금이 더 많음"
    )
    assert (
        _text(MIXED, ["flows"], "{{compare.amount.USD}}")
        == "USD 합계 비교 입금 27,250.50 USD, 출금 24,500.25 USD · 입금이 더 많음"
    )


def test_compare_amount_absent_when_currency_on_one_side_only() -> None:
    piece = extract(MULTI, "R02_FAN_IN", ["flows"], LABELS)  # 입금만(EUR·USD)
    assert not any(k.startswith("compare.amount.") for k in piece.keys)
    row = {
        "from_account_key": "020_A0000001",
        "to_account_key": S,
        "currency_paid": "USD",
        "currency_received": "USD",
    }
    rows = [
        {**_base(1), **row},
        {
            **_base(2),
            "from_account_key": S,
            "to_account_key": "030_B0000001",
            "currency_paid": "EUR",
            "currency_received": "EUR",
        },
    ]
    piece = extract(build({"transactions": rows}), "R02_FAN_IN", ["flows"], LABELS)
    assert not any(k.startswith("compare.amount.") for k in piece.keys)
    assert "compare.count" in piece.keys


def _base(k: int) -> dict:
    return {
        "transaction_id": k,
        "ts": f"2022-09-02T1{k}:00:00",
        "amount_paid": "100.00",
        "amount_received": "100.00",
        "payment_format": "ACH",
        "is_self_transfer": False,
    }


def test_vs_baseline_is_code_rendered_only_with_baseline() -> None:
    text = _text(
        PATHS, ["score_reasons"], "{{observations.inflow_outflow_ratio_2h.vs_baseline}}", "R05_SCATTER_GATHER"
    )
    assert text == "inflow_outflow_ratio_2h 관측값 1 · 평소 기준값 0.4 · 기준값보다 높음"
    fan_in = Facts.model_validate(load_json(FIXTURES / "facts_ask_fan_in.json"))
    piece = extract(fan_in, "R02_FAN_IN", ["score_reasons"], LABELS)
    assert not any(k.endswith(".vs_baseline") for k in piece.keys)


# ---------- 자리표 밖 비교 꼴 ----------

PIECE = extract(MIXED, "R02_FAN_IN", ["flows"], LABELS)


def _check(answer: str):
    (c,) = run(render(answer, PIECE, LABELS), "입금이 출금보다 많아?", "CASE-2022-000057")
    return c


@pytest.mark.parametrize(
    "answer",
    [
        "{{inbound.amount.USD|이}} {{outbound.amount.USD}}보다 적어요.",  # O1 뒤집힌 비교(추가 검토 2)
        "{{inbound.amount.USD|과}} {{outbound.amount.USD|을}} 견주면 입금이 더 많아요.",
        "{{compare.count|이에요}}. 평소보다 높아요.",
        "{{inbound.count|과}} {{outbound.count|은}} 비슷해요.",
        "{{inbound.count|과}} {{outbound.count|은}} 차이가 커요.",
        "{{inbound.count|과}} {{outbound.count|이}} 같아요.",
        "{{inbound.count|은}} 적어요. {{outbound.count|이에요}}.",
    ],
)
def test_comparison_outside_slots_is_unverified(answer: str) -> None:
    c = _check(answer)
    assert not c.match and c.draft_value.startswith("자리표 밖 비교"), answer


@pytest.mark.parametrize(
    "answer",
    [
        "{{compare.amount.USD|이에요}}. 보다 자세히 알려면 거래 내역을 보세요.",
        "{{compare.count|이에요}}. 자료가 부족한 것 같아요.",
        "{{compare.amount.USD|이에요}}. 보다 정확히는 담당자가 확인해요.",
    ],
)
def test_ordinary_boda_and_hedge_are_not_comparisons(answer: str) -> None:
    """비교로 잘못 읽지 않음만 봄 — 끝맺음(`보세요`·`같아요`·`확인해요`)은 추가 검토 3 허용 목록 밖이라 서술어로 막힘."""
    c = _check(answer)
    assert not (c.draft_value or "").startswith("자리표 밖 비교"), answer
    assert c.draft_value.startswith("자리표 밖 서술어"), answer


def test_service_compare_slot_answer_and_evidence() -> None:
    llm = StubLlm(
        [plan_text("FACT", None, ["flows"]), answer_text(True, "금액은 {{compare.amount.USD|이에요}}.")]
    )
    svc, _ = build_service(llm, facts=MIXED)
    res = svc.ask(ask_request("입금이 출금보다 많아?", rule_id="R02_FAN_IN"))
    assert res.status is AskStatus.ANSWERED and res.cites == ["compare.amount.USD"]
    assert res.evidence_ids == sorted({*MIXED.inbound.transaction_ids, *MIXED.outbound.transaction_ids})


# ---------- 판정 도구 — 비교 꼴을 값으로 따로 판정(서비스와 코드 공유 없음) ----------


def _verdict(raw: str) -> str:
    it = GAPS["O1"]
    svc, _ = build_service(FixedAnswer(recorded(), raw), facts=facts_for(it))
    res = svc.ask(ask_request(it["question"], rule_id=it["rule_id"]))
    piece = extract(facts_for(it), it["rule_id"], res.generation_meta.bundles, LABELS)
    return judge.verdict(
        it,
        "ANSWERED",  # 서비스가 막는 꼴도 판정 도구가 따로 보는지 시험(상태는 강제)
        res.answer or ask_judge_text.judge_text(raw, piece, LABELS),
        ask_judge_text.judge_text(raw, piece, LABELS),
        ask_judge_text.slot_direction_conflicts(raw, piece) > 0
        or ask_judge_text.comparison_wrong(raw, piece),
        ask_judge_text.slot_direction_unclear(raw, piece),
    )


def test_judge_catches_reversed_comparison_by_values() -> None:
    assert _verdict("{{inbound.amount.USD|이}} {{outbound.amount.USD}}보다 적어요.") == judge.WRONG


def test_judge_accepts_compare_slot_answer() -> None:
    assert _verdict("금액은 {{compare.amount.USD|이에요}}. 건수는 {{compare.count|이에요}}.") == judge.RIGHT
