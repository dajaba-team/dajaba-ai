"""질문 답변 고치기 — 방향 칸·계획 보강·이어지는 질문·금액 정확 값 (SCRUM-358·359, 정본 docs/str/04·06).

녹화 없이 가짜 LLM·픽스처 facts 로만. v2 녹화 재생은 ★B3.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from aml_ai.shared.schemas.str import AskStatus, Facts
from aml_ai.str.domain import ask_checks
from aml_ai.str.domain.ask_bundles import ask_fact_keys, extract, with_flows
from aml_ai.str.domain.ask_question import is_follow_up, mask_question
from aml_ai.str.domain.constants_ask import ASK_NO_LLM_MODEL
from aml_ai.str.domain.fact_keys import fact_keys
from aml_ai.str.domain.facts_direction import counterparties_by_direction
from aml_ai.str.domain.masking import mask_for_llm
from aml_ai.str.domain.models import Transaction
from aml_ai.str.infrastructure.display_labels import load_display_labels
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


# ---------- 자료 ----------


def test_counterparties_by_direction_counts_each_side() -> None:
    """입금 2(같은 은행 1) · 출금 3 · 겹친 계좌 1 은 양쪽에 셈."""
    inbound = [_tx(1, "10_AAAA1111", S), _tx(2, "20_BBBB2222", S), _tx(3, "20_BBBB2222", S)]
    outbound = [_tx(4, S, "20_BBBB2222"), _tx(5, S, "30_CCCC3333"), _tx(6, S, "30_DDDD4444")]
    got = counterparties_by_direction(inbound, outbound, S)
    assert (got.inbound.count, got.inbound.same_bank_accounts, got.inbound.other_bank_accounts) == (2, 1, 1)
    assert (got.outbound.count, got.outbound.same_bank_accounts, got.outbound.other_bank_accounts) == (
        3,
        0,
        3,
    )


def test_field_not_in_llm_masking_nor_draft_keys() -> None:
    facts = _mixed()
    assert "counterparties_by_direction" not in mask_for_llm(facts)
    assert not any(k.startswith("counterparties_by_direction") for k in fact_keys(facts))


def test_counterparties_bundle_carries_field_and_ask_keys() -> None:
    facts = _mixed()
    piece = extract(facts, "R02_FAN_IN", ["counterparties"], load_display_labels())
    assert piece.content["counterparties_by_direction"]["inbound"]["count"] == 2
    assert "counterparties_by_direction.outbound.other_bank_accounts" in piece.keys
    keys = ask_fact_keys(facts)
    assert keys["counterparties_by_direction.inbound.count"] == list(facts.inbound.transaction_ids)
    assert ask_checks.cited_evidence_ids(facts, ["counterparties_by_direction.outbound.count"]) == [3, 4, 5]


def test_old_snapshot_bundle_has_no_field() -> None:
    facts = _mixed().model_copy(update={"counterparties_by_direction": None})
    piece = extract(facts, "R02_FAN_IN", ["counterparties"], load_display_labels())
    assert "counterparties_by_direction" not in piece.content
    assert not any(k.startswith("counterparties_by_direction") for k in piece.keys)


# ---------- 계획 보강 ----------


@pytest.mark.parametrize(
    ("bundles", "question", "want"),
    [
        (["counterparties"], "입금 상대 계좌는 몇 개입니까?", ["counterparties", "flows"]),
        (["paths"], "자금이 지나간 경로는 몇 개야?", ["paths", "flows"]),
        (["flows"], "입금 거래는 몇 건이야?", ["flows"]),
        (["counterparties"], "상대 계좌는 몇 개야?", ["counterparties"]),
        (
            ["subject", "counterparties", "paths"],
            "입금 상대 계좌는 몇 개야?",
            ["subject", "counterparties", "paths"],
        ),
    ],
)
def test_with_flows(bundles: list[str], question: str, want: list[str]) -> None:
    """마지막 줄: 계획이 3개(flows 없음) + 방향 낱말 → 안 붙음 · 3개 그대로(meta ≤3, ★B md 답 1)."""
    assert with_flows(bundles, mask_question(question)) == want


def test_service_meta_bundles_include_added_flows_plan_row_keeps_llm_pick() -> None:
    llm = StubLlm(
        responses=[
            plan_text("FACT", None, ["counterparties"]),
            answer_text(
                answer="입금 상대 계좌는 2개예요.", cites=["counterparties_by_direction.inbound.count"]
            ),
        ]
    )
    svc, repo = build_service(llm, facts=_mixed())
    res = svc.ask(ask_request("입금 상대 계좌는 몇 개야?", rule_id="R02_FAN_IN"))
    assert res.status is AskStatus.ANSWERED and res.evidence_ids == [1, 2]
    assert res.generation_meta.bundles == ["counterparties", "flows"]
    plan_row = repo.saved[0]["response_payload"]["plan"]
    assert plan_row["bundles"] == ["counterparties"] and "source" not in plan_row


def test_service_wrong_direction_answer_is_unverified() -> None:
    """346 발견 모양 — 전체 상대 수(4)를 입금 상대로 쓴 답은 UNVERIFIED."""
    llm = StubLlm(
        responses=[
            plan_text("FACT", None, ["counterparties"]),
            answer_text(answer="입금 상대는 계좌 4개로 보여요.", cites=["counterparties.count"]),
        ]
    )
    svc, _ = build_service(llm, facts=_mixed())
    assert svc.ask(ask_request("입금 상대 계좌는 몇 개야?")).status is AskStatus.UNVERIFIED


# ---------- 이어지는 질문 ----------


@pytest.mark.parametrize(
    ("question", "blocked"),
    [
        ("그 중에 제일 큰 건?", True),  # 359 C2 — `건` 단독은 주제 아님
        ("그럼 출금은?", False),  # 359 C1 — `출금` 주제
        ("이거 자금세탁 맞지? 보고해야 해?", False),  # 18개 O3 — `이거` 머리 아님
        ("그중 제일 큰 거?", True),
        ("그 다음은?", True),
        ("그럼 3건은 언제야?", False),  # `그럼` + 숫자+건 → 계획으로
        ("그럼 거래는 총 몇 건이야?", False),  # 추가 검토 1 M3 — `거래`·`몇 건` 주제
        ("그중 3건만 합치면?", True),  # 추가 검토 1 M3 — `그중` 은 앞 답 집합, 주제 상관없이 범위 밖
        ("그 중 입금은?", True),
        ("그럼 그중 3건만 합치면?", True),  # 추가 검토 2 — 접속어 뗀 뒤 그중류
        ("그럼 이 케이스의 탐지 유형은?", False),  # 추가 검토 2 — `이 케이스`·`유형` 주제
        ("그럼 건수는?", False),
        ("그럼 금액은?", False),
        ("그러면 그 중에서 가장 처음에 있었던 그것은 무엇이었어?", False),  # 20자 넘음
        ("왜 이 룰에 걸렸어?", False),
    ],
)
def test_is_follow_up(question: str, blocked: bool) -> None:
    assert is_follow_up(question) is blocked


def test_service_follow_up_ends_without_llm() -> None:
    llm = StubLlm(responses=[])  # 부르면 IndexError
    svc, repo = build_service(llm, facts=_mixed())
    res = svc.ask(ask_request("그 중에 제일 큰 건?"))
    assert (res.status, res.out_of_scope_reason.value) == (AskStatus.OUT_OF_SCOPE, "OUTSIDE_CASE")
    meta = res.generation_meta
    assert (meta.llm_model, meta.prompt_version, meta.bundles) == (ASK_NO_LLM_MODEL, None, [])
    assert (meta.tokens_in, meta.tokens_out, meta.latency_ms) == (0, 0, 0)
    assert llm.calls == []
    assert repo.saved[0]["response_payload"]["plan"]["source"] == "code"
    assert "source" not in res.model_dump(mode="json")
