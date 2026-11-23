"""추가 검토 1(SCRUM-362) 반례 — 답 경로. 고치기 전에 먼저 넣어 실패를 확인한 테스트 (정본 docs/str/04·06). LLM 없음.

1 방향 이름표 우세/만 · 2 자리표 밖 수사·한자어 수량 · 3 방향+지표 · 5 빈 목록 값. 판정·계획 비교는 `test_ask_review_362_1b.py`.
"""

from __future__ import annotations

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from aml_ai.str.domain.ask_bundles import extract
from aml_ai.str.domain.ask_checks import run
from aml_ai.str.domain.ask_scope import AskScope
from aml_ai.str.domain.ask_slots import render
from aml_ai.str.infrastructure.ask_llm import key_line
from aml_ai.str.infrastructure.display_labels import load_display_labels
from tests.conftest import FIXTURES, load_json
from tests.str.ask_recorded_support import facts_for
from tests.str.ask_service_support import StubLlm, answer_text, ask_request, build_service, plan_text
from tests.str.facts_support import CASES, build

LABELS = load_display_labels()
WHOLE = AskScope(whole_alert=True, ownership_known=True)  # 배타 이름표 시험 — 범위 확인됨(추가 검토 3 H3)
S = CASES["subject"]["account_key"]
MIXED = Facts.model_validate(load_json(FIXTURES / "facts_ask_mixed.json"))


@pytest.fixture(autouse=True)
def _skip_end_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import aml_ai.str.application.ask_service as mod

    monkeypatch.setattr(mod, "end_read", lambda _s: None)


def _rows(n_in: int, n_out: int) -> list[dict]:
    """대상 계좌 S 기준 입금 n_in · 출금 n_out 거래(상대는 모두 다른 타행 계좌)."""
    rows = []
    for k in range(n_in + n_out):
        other = f"0{20 + k}_A{k:07d}"
        src, dst = (other, S) if k < n_in else (S, other)
        rows.append(
            {
                "transaction_id": k + 1,
                "ts": f"2022-09-02T{10 + k:02d}:00:00",
                "from_account_key": src,
                "to_account_key": dst,
                "amount_paid": "100.00",
                "currency_paid": "USD",
                "amount_received": "100.00",
                "currency_received": "USD",
                "payment_format": "ACH",
                "is_self_transfer": False,
            }
        )
    return rows


def _direction_text(n_in: int, n_out: int, bundles: list[str]) -> str:
    facts = build({"transactions": _rows(n_in, n_out)})
    return render("{{direction}}", extract(facts, "R02_FAN_IN", bundles, LABELS, scope=WHOLE), LABELS).text


# ---------- 1 방향 이름표: INBOUND·OUTBOUND 는 우세, "만" 은 반대 방향 0건이 조각으로 확인될 때만 ----------


@pytest.mark.parametrize(
    ("n_in", "n_out", "bundles", "want"),
    [
        (2, 1, ["flows"], "거래 방향 입금 우세"),
        (1, 2, ["flows"], "거래 방향 출금 우세"),
        (3, 0, ["flows"], "거래 방향 대외 입금만"),  # 추가 검토 2 H1 — 범위(대외)를 이름표에
        (0, 2, ["flows"], "거래 방향 대외 출금만"),
        (3, 0, ["formats"], "거래 방향 입금 우세"),  # 조각에 건수가 없어 0건을 확인 못 함
    ],
    ids=["2:1", "1:2", "3:0", "0:2", "3:0-formats"],
)
def test_direction_label_dominant_or_only(n_in: int, n_out: int, bundles: list[str], want: str) -> None:
    assert _direction_text(n_in, n_out, bundles) == want


# ---------- 2 자리표 밖 수사·한자어 수량·금액 단위·공백 변형 ----------

PIECE = extract(MIXED, "R02_FAN_IN", ["flows", "counterparties"], LABELS)


@pytest.mark.parametrize(
    "tail",
    [
        "출금은 열두 건이에요.",
        "상대는 스물세 개예요.",
        "합계는 백만 원이에요.",
        "삼천 달러가 나갔어요.",
        "오십 건이에요.",
        "만 원이 들어왔어요.",
        "열두  건이에요.",
        "스물 세 개예요.",
        "서른다섯 번 보냈어요.",
    ],
)
def test_compound_and_sino_numerals_are_outside_numbers(tail: str) -> None:
    (c,) = run(render("{{inbound.count|이에요}}. " + tail, PIECE, LABELS), "입금 거래는?", "CASE-2022-000057")
    assert not c.match and c.draft_value.startswith("자리표 밖 숫자"), tail


@pytest.mark.parametrize(
    "tail",
    [
        "이 건은 입금만 있어요.",
        "이 계좌의 거래예요.",
        "둘 다 확인돼요.",
        "천천히 보면 확인돼요.",  # 끝맺음은 허용 목록 안으로(추가 검토 3) — 여기선 숫자 오탐만 봄
        "어떤 조건을 충족했는지는 확인하기 어려워요.",  # 조 + 건 오탐(18 W1 v4 녹화)
        "조회 화면에서 확인돼요.",
    ],
)
def test_ordinary_words_are_not_numbers(tail: str) -> None:
    (c,) = run(render("{{inbound.count|이에요}}. " + tail, PIECE, LABELS), "입금 거래는?", "CASE-2022-000057")
    assert c.match, tail


def test_slot_plus_fake_quantity_is_unverified_in_service() -> None:
    llm = StubLlm(
        [
            plan_text("FACT", None, ["flows"]),
            answer_text(True, "{{inbound.count|이에요}}. 출금은 열두 건이에요."),
        ]
    )
    svc, _ = build_service(llm, facts=MIXED)
    res = svc.ask(ask_request("입금 거래는 몇 건이야?", rule_id="R02_FAN_IN"))
    assert (res.status, res.answer, res.cites, res.evidence_ids) == (AskStatus.UNVERIFIED, None, [], [])


# ---------- 3 방향 + 지표 ----------


def _status(question: str, answer: str, bundles: list[str], facts: Facts = MIXED) -> AskStatus:
    llm = StubLlm([plan_text("FACT", None, bundles), answer_text(True, answer)])
    svc, _ = build_service(llm, facts=facts)
    return svc.ask(ask_request(question, rule_id="R02_FAN_IN")).status


CB = "counterparties_by_direction"


def test_same_side_other_metric_does_not_cover_opposite_counterparty() -> None:
    """입금 상대 질문 — 입금 거래 건수 키로는 출금 상대 수를 덮지 못함."""
    answer = "{{inbound.count|이에요}}. {{" + CB + ".outbound.count|이에요}}."
    assert _status("입금 상대 계좌는 몇 개야?", answer, ["counterparties"]) is AskStatus.UNVERIFIED


def test_premise_correction_with_zero_same_side_passes() -> None:
    """P4 꼴 — 그 방향 0건 키로 바로잡은 뒤 반대 방향 값."""
    fan_in = facts_for({"facts_case": "fan_in"})
    answer = "질문하신 출금 방향의 거래는 없어요. {{outbound.count|이}} 확인되며, {{inbound.amount.USD|이}} 확인돼요."
    assert _status("보낸 돈은 통화별로 합계가 얼마야?", answer, ["flows"], fan_in) is AskStatus.ANSWERED


def test_two_direction_comparison_passes() -> None:
    """양방향 비교 — (B1) 부터 비교는 compare 자리표로(LLM 글의 `더 많아` 는 막힘)."""
    blocked = "{{inbound.amount.USD|과}} {{outbound.amount.USD|을}} 견주면 입금이 더 많아 보여요."
    assert _status("입금이 출금보다 많아?", blocked, ["flows"]) is AskStatus.UNVERIFIED
    assert (
        _status("입금이 출금보다 많아?", "금액은 {{compare.amount.USD|이에요}}.", ["flows"])
        is AskStatus.ANSWERED
    )


def test_english_incoming_question_with_outbound_key_only_is_unverified() -> None:
    q = "How many incoming transactions are there?"
    assert _status(q, "{{outbound.count|이에요}}.", ["flows"]) is AskStatus.UNVERIFIED
    assert _status(q, "{{inbound.count|이에요}}.", ["flows"]) is AskStatus.ANSWERED


# ---------- 5 빈 목록 값 ----------


def _internal_only() -> Facts:
    rows = [
        {**_rows(1, 0)[0], "from_account_key": "10_S0000002", "to_account_key": S},  # 같은 엔티티 계좌 → 내부
    ]
    return build({"transactions": rows})


def test_empty_payment_formats_is_not_rendered_nor_offered() -> None:
    facts = _internal_only()
    piece = extract(facts, "R02_FAN_IN", ["formats"], LABELS)
    assert "payment_formats" in piece.keys and piece.content["payment_formats"] == []
    s = render("{{payment_formats|이에요}}", piece, LABELS)
    assert s.errors == 1 and s.keys == ()
    assert key_line("payment_formats", piece, LABELS) is None  # <fact_keys> 에서 빠짐
